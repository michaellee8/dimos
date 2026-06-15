{
  description = "Point-LIO native module (topic-isolated: consumes Imu + PointCloud2)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    dimos-lcm = {
      url = "github:dimensionalOS/dimos-lcm/main";
      flake = false;
    };
    fast-lio = {
      url = "github:dimensionalOS/dimos-module-fastlio2/pointlio";
      flake = false;
    };
    lcm-extended = {
      url = "github:jeff-hykin/lcm_extended";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-utils.follows = "flake-utils";
    };
  };

  outputs = { self, nixpkgs, flake-utils, dimos-lcm, fast-lio, lcm-extended, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # Overlay fixes for darwin-broken nixpkgs recipes in our transitive
        # dep chain (pcl → vtk → pdal → tiledb → libpqxx).  Each of these
        # should go upstream; kept here so we can build in the meantime.
        #
        # Gated on isDarwin so Linux keeps binary-cache hits for the stock
        # libpqxx / tiledb / pdal / vtk / pcl derivations.  Applying the
        # override on Linux would change their input hashes and force a
        # from-source rebuild of the whole chain for no benefit.
        darwinDepFixes = final: prev:
          if !prev.stdenv.isDarwin then { } else {
            # libpqxx: postgresqlTestHook is in nativeCheckInputs
            # unconditionally and that package is marked broken on darwin.
            # The list is eagerly evaluated, so simply referencing it aborts
            # eval.  Upstream fix is to wrap the list in
            # `lib.optionals (meta.availableOn ...)`.
            libpqxx = prev.libpqxx.overrideAttrs (_old: {
              nativeCheckInputs = [ ];
              doCheck = false;
            });
            # tiledb: darwin-only patch `generate_embedded_data_header.patch`
            # targets a file that doesn't exist in tiledb 2.30.0 (the
            # upstream code path was reworked and `file(ARCHIVE_CREATE ...)`
            # is no longer used anywhere in the source).  Filter out only
            # that patch — don't drop everything, in case nixpkgs adds an
            # unrelated security patch in a future bump.
            tiledb = prev.tiledb.overrideAttrs (old: {
              patches = builtins.filter
                (p: !(prev.lib.hasSuffix "generate_embedded_data_header.patch" (toString p)))
                (old.patches or [ ]);
            });
          };
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ darwinDepFixes ];
        };
        lcm = lcm-extended.packages.${system}.lcm;

        # Shared native-module helper header (dimos_native_module.hpp).
        common = ../../common;

        pointlio_native = pkgs.stdenv.mkDerivation {
          pname = "pointlio_native";
          version = "0.2.0";

          src = ./.;

          nativeBuildInputs = [ pkgs.cmake pkgs.pkg-config ];
          buildInputs = [
            lcm
            pkgs.glib
            pkgs.eigen
            pkgs.pcl
            pkgs.yaml-cpp
            pkgs.glog
            pkgs.boost
            pkgs.llvmPackages.openmp
          ];

          cmakeFlags = [
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"
            "-DFETCHCONTENT_SOURCE_DIR_DIMOS_LCM=${dimos-lcm}"
            "-DFASTLIO_DIR=${fast-lio}"
            "-DCOMMON_DIR=${common}"
          ];
        };
      in {
        packages = {
          default = pointlio_native;
          inherit pointlio_native;
        };
      });
}
