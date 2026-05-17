meta:
  id: graph_nodes3d
  title: dimos GraphNodes3D
  endian: be
  license: Apache-2.0
  ks-version: '0.10'

doc: |
  This file is the source-of-truth for the binary layout of GraphNodes3D.
  This allows automated generation of Rust,Go,C++,C#,Ruby,Perl,etc

  A bare list of `node3d` (same wire layout as the nodes in `Graph3D`),
  with no edges. Use when a producer only wants to publish poses
  (e.g. keyframe poses, frontier points, navpoints) without graph
  connectivity.

  `metadata_id` is a caller-defined enum:
    - ex: far_planner nodes: 0=normal, 1=odom, 2=goal, 3=frontier, 4=navpoint

seq:
  - id: node_count
    type: u8
    doc: Number of nodes in the `nodes` array.
  - id: timestamp
    type: f8
    doc: Seconds since epoch (POSIX time). Snapshot time.
  - id: nodes
    type: node3d
    repeat: expr
    repeat-expr: node_count

types:
  pose_stamped:
    doc: |
      Mirror of `geometry_msgs/PoseStamped`. `frame_id` is utf-8 encoded
      and prefixed with its byte length (uint32, big-endian). Position
      and orientation are 7 doubles total.
    seq:
      - id: ts
        type: f8
      - id: frame_id_len
        type: u4
      - id: frame_id
        type: str
        size: frame_id_len
        encoding: utf-8
      - id: pos_x
        type: f8
      - id: pos_y
        type: f8
      - id: pos_z
        type: f8
      - id: quat_x
        type: f8
      - id: quat_y
        type: f8
      - id: quat_z
        type: f8
      - id: quat_w
        type: f8

  node3d:
    seq:
      - id: pose
        type: pose_stamped
      - id: id
        type: u8
        doc: Stable identifier.
      - id: metadata_id
        type: u8
        doc: Caller-defined node-type enum.
