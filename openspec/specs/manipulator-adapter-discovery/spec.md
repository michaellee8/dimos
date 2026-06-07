## Purpose

Define lazy manipulator adapter discovery behavior so adapter keys remain listable in partial installations without importing unselected hardware SDKs.

## Requirements

### Requirement: Metadata-only manipulator adapter listing

DimOS SHALL list registered manipulator adapter keys without importing unselected adapter implementation modules.

#### Scenario: Listing adapters in a partial installation
- **GIVEN** a DimOS environment where one or more optional manipulator hardware SDKs are not installed
- **WHEN** a user imports the manipulator adapter registry and asks for available adapter keys
- **THEN** DimOS SHALL return the known adapter keys whose lightweight registry metadata is available
- **AND** DimOS MUST NOT import unselected adapter implementation modules only to produce that list.

#### Scenario: Unrelated adapter remains discoverable
- **GIVEN** an optional binding required by one manipulator adapter is not importable
- **WHEN** a user lists manipulator adapters without selecting that adapter
- **THEN** DimOS SHALL continue discovering unrelated manipulator adapters
- **AND** missing optional dependency errors SHALL NOT prevent unrelated adapter keys from appearing.

### Requirement: Selected manipulator adapter loading

DimOS SHALL import and instantiate only the manipulator adapter selected by `adapter_registry.create(name, **kwargs)`.

#### Scenario: Creating a selected adapter
- **GIVEN** a registered manipulator adapter key and constructor arguments for that adapter
- **WHEN** a user calls `adapter_registry.create()` with that key
- **THEN** DimOS SHALL resolve the selected adapter implementation
- **AND** DimOS SHALL instantiate the selected adapter with the provided arguments.

#### Scenario: Unknown adapter name
- **GIVEN** a manipulator adapter key is not registered
- **WHEN** a user calls `adapter_registry.create()` with that key
- **THEN** DimOS SHALL fail with an error that identifies the unknown adapter
- **AND** the error SHALL include the currently available adapter keys.

#### Scenario: Broken selected adapter registration
- **GIVEN** a manipulator adapter key is registered to an implementation path that cannot be resolved
- **WHEN** a user selects that adapter key
- **THEN** DimOS SHALL fail with an actionable selected-adapter error
- **AND** the error SHALL identify the selected adapter key or its configured implementation path.

### Requirement: Stable manipulator adapter keys

DimOS SHALL preserve existing built-in manipulator adapter keys across the lazy discovery migration.

#### Scenario: Existing adapter keys remain available
- **GIVEN** a user has a hardware configuration or blueprint that selects an existing built-in manipulator adapter key
- **WHEN** DimOS discovers manipulator adapters after this change
- **THEN** that key SHALL remain available if its lightweight registry metadata is present
- **AND** users SHALL NOT need to rename existing manipulator adapter selections for this registry migration.
