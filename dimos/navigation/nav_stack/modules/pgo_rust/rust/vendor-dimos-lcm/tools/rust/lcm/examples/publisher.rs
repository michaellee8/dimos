// Simple LCM Publisher Example
// Publishes Vector3 messages at 10 Hz

use dimos_lcm::Lcm;
use lcm_msgs::geometry_msgs::Vector3;
use tokio::time::{sleep, Duration, Instant};

const TOPIC: &str = "/vector#geometry_msgs.Vector3";

#[tokio::main]
async fn main() {
    let lcm = Lcm::new().await.expect("Failed to create Lcm");

    println!("Publishing Vector3 on {TOPIC}");
    println!("Press Ctrl+C to stop\n");

    let mut t: f64 = 0.0;
    let mut last = Instant::now();

    loop {
        let vec = Vector3 {
            x: t.sin() * 5.0,
            y: t.cos() * 5.0,
            z: t,
        };

        let interval = last.elapsed();
        last = Instant::now();

        lcm.publish(TOPIC, &vec.encode()).await.unwrap();

        println!(
            "Published: x={:.2} y={:.2} z={:.2} (interval {:.1}ms)",
            vec.x,
            vec.y,
            vec.z,
            interval.as_secs_f64() * 1000.0
        );

        t += 0.1;
        sleep(Duration::from_millis(100)).await;
    }
}
