//! Pure Rust LCM (Lightweight Communications and Marshalling) transport.
//!
//! Provides UDP multicast publish/subscribe for LCM messages.
//! No system LCM library required.
//!
//! # Example
//!
//! ```no_run
//! use dimos_lcm::Lcm;
//!
//! #[tokio::main]
//! async fn main() {
//!     let mut lcm = Lcm::new().await.unwrap();
//!
//!     // Publish
//!     let data = vec![1, 2, 3];
//!     lcm.publish("EXAMPLE", &data).await.unwrap();
//!
//!     // Receive
//!     let msg = lcm.recv().await.unwrap();
//!     println!("{}: {} bytes", msg.channel, msg.data.len());
//! }
//! ```

mod transport;

pub use transport::{Lcm, LcmOptions, ReceivedMessage};
