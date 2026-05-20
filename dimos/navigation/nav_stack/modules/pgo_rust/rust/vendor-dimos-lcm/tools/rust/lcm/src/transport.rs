use byteorder::{BigEndian, ByteOrder};
use socket2::{Domain, Protocol, Socket, Type};
use tokio::net::UdpSocket;
use std::collections::HashMap;
use std::io;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4};
use std::sync::Mutex;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Instant;

const MAGIC_SHORT: u32 = 0x4c433032; // "LC02"
const MAGIC_LONG: u32 = 0x4c433033;  // "LC03"
const SHORT_HEADER_SIZE: usize = 8;
const FRAGMENT_HEADER_SIZE: usize = 20;
const MAX_DATAGRAM_SIZE: usize = 65507;

// Reassembly buffer caps. Mirrors the C LCM library's
// MAX_FRAG_BUF_TOTAL_SIZE / MAX_NUM_FRAG_BUFS in `udpm_util.h`. When either
// limit is exceeded, the least-recently-updated entry is evicted to make
// room — preventing the reassembly map from growing unbounded when fragments
// are dropped at the UDP layer (any of N datagrams lost = the other N-1
// stuck in the map). Without eviction, a single dropped packet leaks ~500 KB
// forever, and over a sustained large-message stream the map fills, lock
// contention degrades the receive thread, and drop rates cascade.
const MAX_FRAG_BUF_TOTAL_BYTES: usize = 16 * 1024 * 1024; // 16 MiB
const MAX_NUM_FRAG_BUFS: usize = 1000;

/// Default LCM multicast group address.
pub const DEFAULT_MULTICAST_GROUP: Ipv4Addr = Ipv4Addr::new(239, 255, 76, 67);
/// Default LCM multicast port.
pub const DEFAULT_PORT: u16 = 7667;

static SEQ: AtomicU32 = AtomicU32::new(0);


struct FragmentBuffer {
    channel: String,
    num_fragments: u16,
    received: u16,
    data: Vec<u8>,
    /// Monotonic time of the last fragment arrival on this entry. Used to
    /// pick the LRU entry for eviction when the reassembly map fills.
    last_update: Instant,
}

/// Container for in-flight fragment buffers, with LRU eviction. Wraps a
/// `HashMap` keyed by `(sender, seqno)` and tracks total buffered bytes so
/// we can enforce both an entry-count cap and a memory cap. Mirrors the
/// behavior of `lcm_frag_buf_store` in upstream LCM's `udpm_util.{c,h}`.
struct FragStore {
    map: HashMap<(SocketAddr, u32), FragmentBuffer>,
    total_bytes: usize,
}

impl FragStore {
    fn new() -> Self {
        Self { map: HashMap::new(), total_bytes: 0 }
    }

    /// Evict the single least-recently-updated entry, returning true if one
    /// was found. Caller loops until both caps are satisfied.
    fn evict_lru(&mut self) -> bool {
        let lru_key = self.map.iter()
            .min_by_key(|(_, fb)| fb.last_update)
            .map(|(key, _)| *key);
        if let Some(key) = lru_key {
            if let Some(fb) = self.map.remove(&key) {
                self.total_bytes = self.total_bytes.saturating_sub(fb.data.len());
                return true;
            }
        }
        false
    }

    /// Ensure both caps are honored. Eviction continues until the store
    /// fits within `max_total_bytes` AND `max_entries`. Called after each
    /// new entry insert.
    fn enforce_caps(&mut self) {
        while (self.total_bytes > MAX_FRAG_BUF_TOTAL_BYTES
            || self.map.len() > MAX_NUM_FRAG_BUFS)
            && self.evict_lru()
        {}
    }
}

/// Configuration for an LCM transport instance.
#[derive(Debug, Clone)]
pub struct LcmOptions {
    /// Multicast group address (default: 239.255.76.67).
    pub multicast_group: Ipv4Addr,
    /// UDP port (default: 7667).
    pub port: u16,
    /// Multicast TTL (default: 1).
    pub ttl: u32,
    /// Network interface to bind to (default: any).
    pub interface: Ipv4Addr,
    /// Receive socket buffer size in bytes. None = leave at OS default
    /// (`net.core.rmem_default`). For high-rate publishers of large
    /// fragmented messages (~500 KB PointCloud2 at 10 Hz), the default
    /// 256 KB is far too small and ~50 % of fragments drop. Set this
    /// to 16-64 MB to retain full streams.
    pub recv_buf_size: Option<usize>,
}

impl Default for LcmOptions {
    fn default() -> Self {
        Self {
            multicast_group: DEFAULT_MULTICAST_GROUP,
            port: DEFAULT_PORT,
            ttl: 1,
            interface: Ipv4Addr::UNSPECIFIED,
            recv_buf_size: None,
        }
    }
}

/// A received LCM message.
#[derive(Debug, Clone)]
pub struct ReceivedMessage {
    /// Channel name.
    pub channel: String,
    /// Encoded message payload.
    pub data: Vec<u8>,
}

/// Returns the first and subsequent payload sizes, and the number of fragments
fn fragment_params(msg_size: usize, channel_len: usize) -> (usize, usize, usize) {
    let first_payload_size = MAX_DATAGRAM_SIZE - FRAGMENT_HEADER_SIZE - channel_len - 1;
    let subsequent_payload_size = MAX_DATAGRAM_SIZE - FRAGMENT_HEADER_SIZE;
    let num_fragments = if msg_size <= first_payload_size {
        1
    } else {
        1 + msg_size.saturating_sub(first_payload_size).div_ceil(subsequent_payload_size)
    };
    (first_payload_size, subsequent_payload_size, num_fragments)
}

/// Pure Rust LCM UDP multicast transport.
pub struct Lcm {
    socket: UdpSocket,
    multicast_addr: SocketAddrV4,
    reassembly: Mutex<FragStore>,
}

impl Lcm {
    /// Create a new LCM transport with default options.
    pub async fn new() -> io::Result<Self> {
        Self::with_options(LcmOptions::default()).await
    }

    /// Create a new LCM transport with custom options.
    pub async fn with_options(opts: LcmOptions) -> io::Result<Self> {
        let s2 = Socket::new(Domain::IPV4, Type::DGRAM, Some(Protocol::UDP))?;
        s2.set_reuse_address(true)?;
        #[cfg(not(target_os = "windows"))]
        s2.set_reuse_port(true)?;
        if let Some(size) = opts.recv_buf_size {
            // socket2's set_recv_buffer_size silently clamps to
            // net.core.rmem_max on Linux. Failing the call is non-fatal;
            // log via stderr and continue with whatever the OS gave us.
            if let Err(err) = s2.set_recv_buffer_size(size) {
                eprintln!(
                    "lcm: failed to set SO_RCVBUF={}: {} (continuing with OS default)",
                    size, err,
                );
            }
        }
        let bind_addr = SocketAddrV4::new(Ipv4Addr::UNSPECIFIED, opts.port);
        s2.bind(&bind_addr.into())?;

        let std_socket: std::net::UdpSocket = s2.into();
        std_socket.set_nonblocking(true)?;
        let socket = UdpSocket::from_std(std_socket)?;

        socket.join_multicast_v4(opts.multicast_group, opts.interface)?;
        socket.set_multicast_ttl_v4(opts.ttl)?;

        Ok(Self {
            socket,
            multicast_addr: SocketAddrV4::new(opts.multicast_group, opts.port),
            reassembly: Mutex::new(FragStore::new()),
        })
    }

    /// Publish encoded message data on the given channel.
    pub async fn publish(&self, channel: &str, data: &[u8]) -> io::Result<()> {
        let channel_bytes = channel.as_bytes();
        let total = SHORT_HEADER_SIZE + channel_bytes.len() + 1 + data.len();
        let seqno = SEQ.fetch_add(1, Ordering::Relaxed);

        if total > MAX_DATAGRAM_SIZE {
            self.publish_fragmented(channel_bytes, data, seqno).await
        } else {
            self.publish_small(channel_bytes, data, seqno).await
        }
    }

    async fn publish_small(&self, channel_bytes: &[u8], data: &[u8], seqno: u32) -> io::Result<()> {
        let total = SHORT_HEADER_SIZE + channel_bytes.len() + 1 + data.len();
        let mut buf = vec![0u8; total];

        BigEndian::write_u32(&mut buf[0..4], MAGIC_SHORT);
        BigEndian::write_u32(&mut buf[4..8], seqno);

        buf[SHORT_HEADER_SIZE..SHORT_HEADER_SIZE + channel_bytes.len()]
            .copy_from_slice(channel_bytes);
        // null terminator already 0 from vec![0u8; ..]
        let payload_start = SHORT_HEADER_SIZE + channel_bytes.len() + 1;
        buf[payload_start..].copy_from_slice(data);

        self.socket.send_to(&buf, self.multicast_addr).await?;
        Ok(())
    }

    async fn publish_fragmented(&self, channel_bytes: &[u8], data: &[u8], seqno: u32) -> io::Result<()> {
        let msg_size = data.len();
        let (first_payload_size, subsequent_payload_size, num_fragments) =
            fragment_params(msg_size, channel_bytes.len());

        let mut payload_offset = 0;

        for fragment_no in 0..num_fragments {
            let is_first = fragment_no == 0;
            let channel_size = if is_first { channel_bytes.len() + 1 } else { 0 };
            let max_payload = if is_first { first_payload_size } else { subsequent_payload_size };
            let payload_len = (msg_size - payload_offset).min(max_payload);

            let datagram_size = FRAGMENT_HEADER_SIZE + channel_size + payload_len;
            let mut buf = vec![0u8; datagram_size];

            BigEndian::write_u32(&mut buf[0..4],   MAGIC_LONG);
            BigEndian::write_u32(&mut buf[4..8],   seqno);
            BigEndian::write_u32(&mut buf[8..12],  msg_size as u32);
            BigEndian::write_u32(&mut buf[12..16], payload_offset as u32);
            BigEndian::write_u16(&mut buf[16..18], fragment_no as u16);
            BigEndian::write_u16(&mut buf[18..20], num_fragments as u16);

            let mut offset = FRAGMENT_HEADER_SIZE;

            if is_first {
                buf[offset..offset + channel_bytes.len()].copy_from_slice(channel_bytes);
                // null terminator already 0
                offset += channel_bytes.len() + 1;
            }

            buf[offset..offset + payload_len]
                .copy_from_slice(&data[payload_offset..payload_offset + payload_len]);

            self.socket.send_to(&buf, self.multicast_addr).await?;
            payload_offset += payload_len;
        }

        Ok(())
    }

    /// Receive one LCM message asynchronously.
    ///
    /// Waits until a complete message arrives, reassembling fragments if necessary.
    pub async fn recv(&self) -> io::Result<ReceivedMessage> {
        let mut buf = vec![0u8; MAX_DATAGRAM_SIZE];
        loop {
            let (n, sender) = self.socket.recv_from(&mut buf).await?;
            let pkt = &buf[..n];

            if pkt.len() < 4 { continue; }
            let magic = BigEndian::read_u32(&pkt[0..4]);

            if magic == MAGIC_SHORT {
                if let Some(msg) = Self::decode_small(pkt)? {
                    return Ok(msg);
                }
            } else if magic == MAGIC_LONG {
                if let Some(msg) = self.process_fragment(sender, pkt)? {
                    return Ok(msg);
                }
            }
            // Unknown magic or incomplete fragment — wait for the next datagram
        }
    }

    fn process_fragment(&self, sender: SocketAddr, buf: &[u8]) -> io::Result<Option<ReceivedMessage>> {
        if buf.len() < FRAGMENT_HEADER_SIZE {
            return Ok(None);
        }

        let seqno           = BigEndian::read_u32(&buf[4..8]);
        let total_size      = BigEndian::read_u32(&buf[8..12]) as usize;
        let fragment_offset = BigEndian::read_u32(&buf[12..16]) as usize;
        let fragment_no     = BigEndian::read_u16(&buf[16..18]);
        let num_fragments   = BigEndian::read_u16(&buf[18..20]);

        let mut offset = FRAGMENT_HEADER_SIZE;

        // First fragment carries the channel name
        let channel = if fragment_no == 0 {
            let channel_end = match buf[offset..].iter().position(|&b| b == 0) {
                Some(pos) => offset + pos,
                None => return Ok(None),
            };
            let ch = String::from_utf8_lossy(&buf[offset..channel_end]).into_owned();
            offset = channel_end + 1;
            Some(ch)
        } else {
            None
        };

        let payload = &buf[offset..];

        let key = (sender, seqno);

        let mut reassembly = self.reassembly.lock().unwrap();
        let is_new = !reassembly.map.contains_key(&key);
        reassembly.map.entry(key).or_insert_with(|| FragmentBuffer {
            channel: channel.clone().unwrap_or_default(),
            num_fragments,
            received: 0,
            data: vec![0u8; total_size],
            last_update: Instant::now(),
        });
        if is_new {
            reassembly.total_bytes = reassembly.total_bytes.saturating_add(total_size);
        }
        let entry = reassembly.map.get_mut(&key).unwrap();

        // First fragment also sets the channel name on an existing entry
        if let Some(ch) = channel {
            entry.channel = ch;
        }

        let end = (fragment_offset + payload.len()).min(total_size);
        entry.data[fragment_offset..end].copy_from_slice(&payload[..end - fragment_offset]);
        entry.received += 1;
        entry.last_update = Instant::now();

        if entry.received == entry.num_fragments {
            let complete = reassembly.map.remove(&key).unwrap();
            reassembly.total_bytes = reassembly.total_bytes.saturating_sub(complete.data.len());
            return Ok(Some(ReceivedMessage {
                channel: complete.channel,
                data: complete.data,
            }));
        }

        // Apply the LRU eviction caps. Done on every fragment so a single
        // long-lived dropped-fragment entry doesn't persist past ~1000
        // subsequent messages or 16 MB of accumulated incomplete payloads.
        // Mirrors lcm_frag_buf_store_add in upstream LCM's udpm_util.c.
        if is_new {
            reassembly.enforce_caps();
        }

        Ok(None)
    }

    fn decode_small(buf: &[u8]) -> io::Result<Option<ReceivedMessage>> {
        if buf.len() < SHORT_HEADER_SIZE || BigEndian::read_u32(&buf[0..4]) != MAGIC_SHORT {
            return Ok(None);
        }
        let channel_start = SHORT_HEADER_SIZE;
        let channel_end = match buf[channel_start..].iter().position(|&b| b == 0) {
            Some(pos) => channel_start + pos,
            None => return Ok(None),
        };
        let channel = String::from_utf8_lossy(&buf[channel_start..channel_end]).into_owned();
        let data = buf[channel_end + 1..].to_vec();
        Ok(Some(ReceivedMessage { channel, data }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_CHANNEL_LEN: usize = 13; // "/test_channel"
    const FIRST_PAYLOAD: usize = MAX_DATAGRAM_SIZE - FRAGMENT_HEADER_SIZE - TEST_CHANNEL_LEN - 1;
    const SUBSEQUENT_PAYLOAD: usize = MAX_DATAGRAM_SIZE - FRAGMENT_HEADER_SIZE;

    #[test]
    fn fragment_count_fits_in_one() {
        let (_, _, n) = fragment_params(FIRST_PAYLOAD, TEST_CHANNEL_LEN);
        assert_eq!(n, 1);
    }

    #[test]
    fn fragment_count_spills_into_two() {
        let (_, _, n) = fragment_params(FIRST_PAYLOAD + 1, TEST_CHANNEL_LEN);
        assert_eq!(n, 2);
    }

    #[test]
    fn fragment_count_spills_into_three() {
        let (_, _, n) = fragment_params(FIRST_PAYLOAD + SUBSEQUENT_PAYLOAD + 1, TEST_CHANNEL_LEN);
        assert_eq!(n, 3);
    }

    #[test]
    fn fragment_count_one_mb() {
        let (_, _, n) = fragment_params(1024 * 1024, TEST_CHANNEL_LEN);
        assert_eq!(n, 17);
    }

    fn make_small_packet(channel: &[u8], payload: &[u8]) -> Vec<u8> {
        let mut buf = vec![0u8; SHORT_HEADER_SIZE + channel.len() + 1 + payload.len()];
        BigEndian::write_u32(&mut buf[0..4], MAGIC_SHORT);
        BigEndian::write_u32(&mut buf[4..8], 0);
        buf[SHORT_HEADER_SIZE..SHORT_HEADER_SIZE + channel.len()].copy_from_slice(channel);
        buf[SHORT_HEADER_SIZE + channel.len() + 1..].copy_from_slice(payload);
        buf
    }

    #[test]
    fn decode_small_known_good() {
        let buf = make_small_packet(b"CHAN", &[1, 2, 3]);
        let msg = Lcm::decode_small(&buf).unwrap().unwrap();
        assert_eq!(msg.channel, "CHAN");
        assert_eq!(msg.data, [1u8, 2, 3]);
    }

    #[test]
    fn decode_small_empty_payload() {
        let buf = make_small_packet(b"CHAN", &[]);
        let msg = Lcm::decode_small(&buf).unwrap().unwrap();
        assert_eq!(msg.channel, "CHAN");
        assert!(msg.data.is_empty());
    }

    #[test]
    fn decode_small_wrong_magic() {
        let mut buf = make_small_packet(b"CHAN", &[1, 2, 3]);
        BigEndian::write_u32(&mut buf[0..4], 0xDEADBEEF);
        assert!(Lcm::decode_small(&buf).unwrap().is_none());
    }

    #[test]
    fn decode_small_truncated() {
        // Shorter than SHORT_HEADER_SIZE
        let buf = vec![0x4C, 0x43, 0x30, 0x32, 0x00];
        assert!(Lcm::decode_small(&buf).unwrap().is_none());
    }

    #[test]
    fn decode_small_missing_null_terminator() {
        // Valid header but channel bytes have no null terminator
        let mut buf = vec![0u8; SHORT_HEADER_SIZE + 4];
        BigEndian::write_u32(&mut buf[0..4], MAGIC_SHORT);
        BigEndian::write_u32(&mut buf[4..8], 0);
        buf[SHORT_HEADER_SIZE..SHORT_HEADER_SIZE + 4].copy_from_slice(b"CHAN");
        assert!(Lcm::decode_small(&buf).unwrap().is_none());
    }

    // --- FragStore (reassembly map) tests ---

    fn make_buf(data_size: usize) -> FragmentBuffer {
        FragmentBuffer {
            channel: String::new(),
            num_fragments: 2,
            received: 0,
            data: vec![0u8; data_size],
            last_update: Instant::now(),
        }
    }

    #[test]
    fn frag_store_evicts_when_over_byte_cap() {
        // Insert entries totaling more than MAX_FRAG_BUF_TOTAL_BYTES,
        // verify the oldest are evicted to bring total under the cap.
        let mut store = FragStore::new();
        let big = MAX_FRAG_BUF_TOTAL_BYTES / 2 + 1; // each entry > half the cap
        for i in 0..3 {
            let buf = make_buf(big);
            store.total_bytes += buf.data.len();
            // Use a u32 seqno; sender is the same for all to test eviction
            // happens regardless of sender identity.
            store.map.insert((SocketAddr::from(([127, 0, 0, 1], 0)), i), buf);
            // Stagger update timestamps so LRU has a stable order.
            std::thread::sleep(std::time::Duration::from_millis(1));
            store.enforce_caps();
        }
        assert!(
            store.total_bytes <= MAX_FRAG_BUF_TOTAL_BYTES,
            "total {} must be <= cap {}",
            store.total_bytes,
            MAX_FRAG_BUF_TOTAL_BYTES,
        );
        assert!(
            store.map.len() < 3,
            "at least one entry must have been evicted; got {} entries",
            store.map.len(),
        );
    }

    #[test]
    fn frag_store_evicts_when_over_entry_cap() {
        // Insert MAX_NUM_FRAG_BUFS + 5 small entries, verify count is
        // bounded at MAX_NUM_FRAG_BUFS after enforce_caps runs.
        let mut store = FragStore::new();
        for i in 0..(MAX_NUM_FRAG_BUFS as u32 + 5) {
            let buf = make_buf(8);
            store.total_bytes += buf.data.len();
            store.map.insert((SocketAddr::from(([127, 0, 0, 1], 0)), i), buf);
            store.enforce_caps();
        }
        assert_eq!(
            store.map.len(),
            MAX_NUM_FRAG_BUFS,
            "entry count must be exactly the cap after enforce_caps",
        );
    }

    #[test]
    fn frag_store_evict_lru_picks_oldest() {
        // The eviction picks the entry whose `last_update` is oldest, not
        // (e.g.) by insertion order or by hash position.
        let mut store = FragStore::new();
        let mut older = make_buf(8);
        older.last_update = Instant::now();
        // Make a slightly newer one
        std::thread::sleep(std::time::Duration::from_millis(2));
        let mut newer = make_buf(8);
        newer.last_update = Instant::now();
        let older_key = (SocketAddr::from(([127, 0, 0, 1], 0)), 1u32);
        let newer_key = (SocketAddr::from(([127, 0, 0, 1], 0)), 2u32);
        store.map.insert(older_key, older);
        store.map.insert(newer_key, newer);
        store.total_bytes = 16;
        assert!(store.evict_lru());
        assert!(
            !store.map.contains_key(&older_key),
            "older entry should have been evicted; map: {:?}",
            store.map.keys().collect::<Vec<_>>(),
        );
        assert!(
            store.map.contains_key(&newer_key),
            "newer entry should still be present",
        );
    }
}
