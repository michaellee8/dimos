# Recording a Map

This walks you through driving a Go2 around a space and capturing everything you need to build a map afterward: the Mid-360 point cloud, Point-LIO odometry, and the camera. You drive, it records, you post-process. That's the whole loop.

If you're on the RealSense rig instead of a Go2, the steps are the same — just use the `mid360_realsense` paths in place of `go2_mid360`.

## What you need

- A Unitree Go2 with a Livox Mid-360 mounted on it
- A computer to do the recording (it talks to the dog over wifi and to the lidar over a wired link)
- A phone with a hotspot
- The Mid-360's USB-ethernet adapter and cable

## 1. Mount the Mid-360

Bolt the Mid-360 to the top of the dog, pointing forward, as level as you reasonably can. The recorder doesn't need a perfect mount — Point-LIO figures out the lidar's motion on its own and stamps every frame with a pose — but a level, rigid mount gives you cleaner data. Don't let it wobble. A loose lidar is the fastest way to ruin a recording.

Run the Mid-360's ethernet to your recording computer. The lidar speaks plain ethernet over a USB adapter, so it's a separate wired link, not part of the wifi.

## 2. Find the lidar's IP and get on its subnet

The Mid-360 ships with a static IP. Each unit's address is derived from its serial number: the last octet is the last two digits of the serial. So a lidar whose serial ends in `71` is at `192.168.1.171`. A factory-default unit sits at `192.168.1.155`. Check the sticker.

If the sticker isn't telling you anything, plug it in, power it on, and watch for its packets:

```bash
sudo tcpdump -ni <your-usb-eth-interface> udp
```

The source IP that starts spamming you is the lidar.

Your computer's wired interface has to live on the same `/24` as the lidar. Set it to `192.168.1.5`:

```bash
sudo nmcli con add type ethernet ifname <your-usb-eth-interface> con-name livox-mid360 \
    ipv4.addresses 192.168.1.5/24 ipv4.method manual
sudo nmcli con up livox-mid360
```

This sticks across reboots, so you only do it once per machine.

## 3. Put the dog and your computer on the same hotspot

The recorder talks to the dog over wifi, so both the dog and your computer need to be on the same network. A phone hotspot is the easy, portable answer.

Turn on your phone's hotspot, then point the dog at it over Bluetooth:

```bash
dimos go2tool connect-wifi --ssid <hotspot-name> --password <hotspot-password>
```

Power the dog on first — it advertises over Bluetooth right away. The command scans, finds the dog, and hands it the wifi credentials. If more than one robot shows up, it'll ask which one.

Now connect your computer to the same hotspot. Then find the dog's IP on it:

```bash
dimos go2tool discover
```

That prints a row per robot it sees. Grab the dog's IP and export it:

```bash
export ROBOT_IP=<the-dog-ip>
```

At this point your computer has two links going at once: wifi to the dog, wired ethernet to the lidar. That's expected.

## 4. Record

Tell the recorder where the lidar is and start it:

```bash
export LIDAR_IP=192.168.1.171   # whatever you found in step 2
uv run python dimos/mapping/recording/go2_mid360/record.py
```

A keyboard-teleop window opens. Drive with WASD, turn with Q/E, `Z` to lie down, `X` to stand. Drive the dog through the whole space you want mapped. A few tips:

- Move at a calm walking pace. Whipping it around blurs scans.
- Close the loop — end where you started, and re-cross your own path a couple times. Those revisits are what let the post-process snap out accumulated drift.
- If you've got AprilTags up, get a clean look at each one more than once. They anchor the final groundtruth.

When you're done, `Ctrl+C` the recorder. It writes everything to a timestamped folder under `recordings/`, e.g. `recordings/2026-06-22_03-15pm-PST/mem2.db`.

You don't fuss with poses while recording — the Point-LIO recorder stamps each lidar frame with the live odometry pose as it goes, so the trajectory is already baked into the recording.

## 5. Post-process

This straightens the recording into a ground-truth map: it detects the AprilTags, runs the AprilTag pose-graph solve plus ICP loop closures to pull out drift, writes the corrected `gt_pointlio_*` streams back into the recording, and opens a before/after `.rrd` in Rerun.

```bash
uv run --no-sync python dimos/mapping/recording/go2_mid360/post_process.py
```

With no argument it grabs the most recent recording. Point it at a specific one if you want:

```bash
uv run --no-sync python dimos/mapping/recording/go2_mid360/post_process.py recordings/2026-06-22_03-15pm-PST
```

It also drops a `gt_pointlio_lidar.pc2.lcm` next to the recording — that's your **relocalization premap**. Point the relocalization module at it to localize a live robot against this map; see [Relocalization](/docs/capabilities/mapping/relocalization.md). Pass `--no-icp`, `--no-lcm`, or `--no-rrd` to skip a stage.

## 6. Sanity-check it

Before you trust a recording, look at it:

```bash
uv run python dimos/mapping/recording/utils/rec_check.py
```

It reports stream rates and how far the odometry traveled. If `pointlio_lidar` or `pointlio_odometry` is empty, or the travel distance is wildly off, something went wrong on the lidar link — recheck the IP and the wired interface and run it again.
