# Manipulation eval

Skill-mode pick-and-place benchmark for `PickAndPlaceModule` over RPC. Writes one JSONL line
per episode to `~/.dimos/eval_runs/`; the same harness runs the pre- and post-SkillResult stacks.

```bash
dimos run xarm-perception-sim-agent              # sim (MUJOCO_GL=egl if headless)
python -m dimos.manipulation.eval.health_check   # confirm scan detects objects
```

```python
from dimos.manipulation.eval.recorder import EpisodeRecorder
from dimos.manipulation.eval.runner import BenchmarkRunner
from dimos.manipulation.eval.suite import BENCHMARK_TRIALS
from dimos.manipulation.eval import report
rec = EpisodeRecorder(hardware="sim")
r = BenchmarkRunner(rec); r.connect(); r.prepare()          # homes the arm, sets the scan pose
r.run_suite(BENCHMARK_TRIALS, n_repeats=3); rec.close()
report.print_report(report.load_episodes(rec.path))
```

Trial object names must match what `scan_objects()` reports — scan once and align `suite.py` first.
For before/after, run on each checkout (`main`, then `80dc44918`), then
`report.sim_to_real_gap(load_episodes(before), load_episodes(after))`.
