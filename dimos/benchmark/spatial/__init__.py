# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Versioned contracts and utilities for the static spatial benchmark corpus."""

from dimos.benchmark.spatial.bundles import BundleInput, BundleResult, SnapshotVariant, write_bundle
from dimos.benchmark.spatial.collision_oracle import (
    CandidateDisposition,
    GeometryCandidateRejectedError,
    GeometryToleranceValidator,
    OracleEvaluation,
    SquareFootprintCollisionOracle,
)
from dimos.benchmark.spatial.config import (
    SPATIAL_BENCHMARK_V1,
    GeometryToleranceConfig,
    LidarNoiseProfile,
    SeedPolicyConfig,
    SpatialBenchmarkConfig,
    SquareFootprintConfig,
    VoxelMapperConfig,
    WorldFrameConfig,
    derive_v1_seed,
)
from dimos.benchmark.spatial.corpus_loader import (
    OracleRecords,
    SpatialCorpusInstance,
    SpatialCorpusLoader,
    SpatialCorpusSelection,
)
from dimos.benchmark.spatial.models import (
    Answer,
    BarrierSegment,
    FreeSpaceModel,
    Geometry,
    Instance,
    Manifest,
    Question,
    ReviewOverride,
    Scene,
    Snapshot,
    SourceProvenance,
    Topology,
    Trajectory,
    write_record_schemas,
)
from dimos.benchmark.spatial.questions import (
    QUESTION_DEFINITION_VERSION,
    TEMPLATE_VERSION,
    PhysicalQuestion,
    executable_definitions,
    generate_physical_questions,
)
from dimos.benchmark.spatial.structured3d import (
    PlaneGeometry,
    SourceAxisTransform,
    Structured3DAnnotation,
    Structured3DError,
    Structured3DImport,
    load_structured3d_scene,
    unique_room_for_marker,
)
from dimos.benchmark.spatial.utilities import (
    canonical_json,
    hash_file_sha256,
    stable_opaque_id,
    validate_relative_path,
)
from dimos.benchmark.spatial.validation import (
    ReleaseValidationError,
    ValidationFailure,
    ValidationReport,
    require_release_complete,
    validate_release,
)
from dimos.benchmark.spatial.viewer import SpatialCorpusViserView, ViserReadOnlyBoundary

__all__ = [
    "QUESTION_DEFINITION_VERSION",
    "SPATIAL_BENCHMARK_V1",
    "TEMPLATE_VERSION",
    "Answer",
    "BarrierSegment",
    "BundleInput",
    "BundleResult",
    "CandidateDisposition",
    "FreeSpaceModel",
    "Geometry",
    "GeometryCandidateRejectedError",
    "GeometryToleranceConfig",
    "GeometryToleranceValidator",
    "Instance",
    "LidarNoiseProfile",
    "Manifest",
    "OracleEvaluation",
    "OracleRecords",
    "PhysicalQuestion",
    "PlaneGeometry",
    "Question",
    "ReleaseValidationError",
    "ReviewOverride",
    "Scene",
    "SeedPolicyConfig",
    "Snapshot",
    "SnapshotVariant",
    "SourceAxisTransform",
    "SourceProvenance",
    "SpatialBenchmarkConfig",
    "SpatialCorpusInstance",
    "SpatialCorpusLoader",
    "SpatialCorpusSelection",
    "SpatialCorpusViserView",
    "SquareFootprintCollisionOracle",
    "SquareFootprintConfig",
    "Structured3DAnnotation",
    "Structured3DError",
    "Structured3DImport",
    "Topology",
    "Trajectory",
    "ValidationFailure",
    "ValidationReport",
    "ViserReadOnlyBoundary",
    "VoxelMapperConfig",
    "WorldFrameConfig",
    "canonical_json",
    "derive_v1_seed",
    "executable_definitions",
    "generate_physical_questions",
    "hash_file_sha256",
    "load_structured3d_scene",
    "require_release_complete",
    "stable_opaque_id",
    "unique_room_for_marker",
    "validate_relative_path",
    "validate_release",
    "write_bundle",
    "write_record_schemas",
]
