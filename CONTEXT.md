# DimOS Deployment Context

This glossary defines the language for DimOS module deployment discussions. It distinguishes coordinator-side planning concepts from target-side runtime ownership concepts.

## Language

**External Module Deployment**:
A DimOS deployment path where a coordinator-visible module contract is backed by an implementation that runs outside the coordinator Python environment.
_Avoid_: isolated package launch, packaged module hack

**External Worker**:
A target-side deployment participant that owns external module runtime handles for one deployment run.
_Avoid_: external manager, runtime entrypoint, direct subprocess

**Worker Manager External**:
The coordinator-side manager that prepares or connects to target-side external workers and coordinates their lifecycle.
_Avoid_: external worker, runtime host

**Package Preparation**:
Target-side materialization of an external module's runtime environment before the module runtime starts.
_Avoid_: coordinator install step, launch side effect

**Module Launch Envelope**:
A serialized handoff from deployment control to an external runtime handle that identifies what module implementation to start and how it should join the DimOS graph.
_Avoid_: pickled module class, live object payload
