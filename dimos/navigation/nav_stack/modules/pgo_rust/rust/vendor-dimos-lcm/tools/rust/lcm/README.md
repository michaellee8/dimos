# dimos-lcm (Rust)

Pure Rust LCM (Lightweight Communications and Marshalling) transport. No system LCM library required.

## Installation

```toml
[dependencies]
dimos-lcm = { git = "https://github.com/dimensionalOS/dimos-lcm.git" }
lcm-msgs = { git = "https://github.com/dimensionalOS/dimos-lcm.git" }
tokio = { version = "1", features = ["full"] }
```

## Quick Start

```rust
use dimos_lcm::Lcm;
use lcm_msgs::geometry_msgs::Vector3;

#[tokio::main]
async fn main() {
    let mut lcm = Lcm::new().await.unwrap();

    // Publish
    let vec = Vector3 { x: 1.0, y: 2.0, z: 3.0 };
    lcm.publish("/vector#geometry_msgs.Vector3", &vec.encode()).await.unwrap();

    // Receive
    let msg = lcm.recv().await.unwrap();
    let vec = Vector3::decode(&msg.data).unwrap();
    println!("{}: x={} y={} z={}", msg.channel, vec.x, vec.y, vec.z);
}
```

## API Reference

#### `Lcm::new() -> io::Result<Lcm>`

Creates a new LCM transport using default multicast settings (`239.255.76.67:7667`).

#### `lcm.publish(channel: &str, data: &[u8]) -> io::Result<()>`

Publishes raw bytes to a channel. Messages larger than a single UDP datagram are automatically fragmented.

#### `lcm.recv() -> io::Result<ReceivedMessage>`

Waits for the next message and returns it. Reassembles fragmented messages automatically.

### `ReceivedMessage`

```rust
pub struct ReceivedMessage {
    pub channel: String,
    pub data: Vec<u8>,
}
```

## Examples

```bash
# In two terminals:
cargo run --example publisher
cargo run --example subscriber
```
