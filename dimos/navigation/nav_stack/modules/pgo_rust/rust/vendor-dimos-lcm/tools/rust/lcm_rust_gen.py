#!/usr/bin/env python3
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

"""LCM Rust Code Generator.

Parses .lcm files and generates Rust structs with encode/decode/hash
matching the LCM wire format used by the TypeScript and Python generators.
"""

import argparse
import ctypes
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys

# ── AST ──────────────────────────────────────────────────────────────────────


@dataclass
class LcmDimension:
    size: str
    is_constant: bool  # True if numeric literal


@dataclass
class LcmMember:
    type: str
    name: str
    dimensions: list[LcmDimension] = field(default_factory=list)


@dataclass
class LcmConstant:
    type: str
    name: str
    value: str


@dataclass
class LcmStruct:
    package: str
    name: str
    members: list[LcmMember] = field(default_factory=list)
    constants: list[LcmConstant] = field(default_factory=list)
    hash: int = 0

    @property
    def full_name(self):
        return f"{self.package}.{self.name}" if self.package else self.name


@dataclass
class LcmFile:
    package: str
    structs: list[LcmStruct] = field(default_factory=list)


# ── Tokenizer ────────────────────────────────────────────────────────────────

TOKEN_RE = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*\/|"[^"]*"|\'[^\']*\'|'
    r"[a-zA-Z_][a-zA-Z0-9_]*|0x[0-9a-fA-F]+|"
    r"[0-9]+\.?[0-9]*(?:[eE][+-]?[0-9]+)?|"
    r"[{}\[\];,=.]"
)


class Tokenizer:
    def __init__(self, source: str):
        self.tokens: list[str] = []
        self.pos = 0
        for m in TOKEN_RE.finditer(source):
            tok = m.group()
            if tok.startswith("//") or tok.startswith("/*"):
                continue
            self.tokens.append(tok)

    def peek(self, offset=0):
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else None

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, expected):
        tok = self.next()
        if tok != expected:
            raise SyntaxError(f"Expected '{expected}', got '{tok}'")

    def has_more(self):
        return self.pos < len(self.tokens)


# ── Parser ───────────────────────────────────────────────────────────────────


def parse_qualified_name(tok: Tokenizer) -> str:
    name = tok.next()
    while tok.peek() == ".":
        tok.next()
        name += "." + tok.next()
    return name


def parse_member(tok: Tokenizer) -> LcmMember:
    type_name = parse_qualified_name(tok)
    name = tok.next()
    dims = []
    while tok.peek() == "[":
        tok.next()
        size = tok.next()
        tok.expect("]")
        dims.append(LcmDimension(size=size, is_constant=size.isdigit()))
    tok.expect(";")
    return LcmMember(type=type_name, name=name, dimensions=dims)


def parse_constants(tok: Tokenizer) -> list[LcmConstant]:
    ctype = tok.next()
    constants = []
    while True:
        name = tok.next()
        tok.expect("=")
        value = tok.next()
        if value == "-":
            value = "-" + tok.next()
        constants.append(LcmConstant(type=ctype, name=name, value=value))
        if tok.peek() != ",":
            break
        tok.next()
    tok.expect(";")
    return constants


def parse_struct(tok: Tokenizer, package: str) -> LcmStruct:
    name = tok.next()
    tok.expect("{")
    members = []
    constants = []
    while tok.peek() != "}":
        if tok.peek() == "const":
            tok.next()
            constants.extend(parse_constants(tok))
        else:
            members.append(parse_member(tok))
    tok.expect("}")
    return LcmStruct(package=package, name=name, members=members, constants=constants)


def parse_file(path: str) -> LcmFile:
    source = Path(path).read_text()
    tok = Tokenizer(source)
    package = ""
    structs = []
    while tok.has_more():
        token = tok.next()
        if token == "package":
            package = tok.next()
            tok.expect(";")
        elif token == "struct":
            structs.append(parse_struct(tok, package))
        elif token == "enum":
            # No enums in current LCM files, skip
            parse_struct(tok, package)
        else:
            raise SyntaxError(f"Unexpected token: {token}")

    for s in structs:
        s.hash = compute_struct_hash(s)

    return LcmFile(package=package, structs=structs)


# ── Hash Algorithm ───────────────────────────────────────────────────────────
# Must match parser.ts lines 58-116 using signed i64 arithmetic.

LCM_PRIMITIVES = {
    "int8_t",
    "int16_t",
    "int32_t",
    "int64_t",
    "float",
    "double",
    "string",
    "boolean",
    "byte",
}


def is_primitive(t: str) -> bool:
    return t in LCM_PRIMITIVES


def hash_update(v: int, c: int) -> int:
    """hash_update: v = ((v << 8) ^ (v >> 55)) + c
    Using signed i64 arithmetic (arithmetic right shift)."""
    # Work in signed i64 via ctypes
    v = ctypes.c_int64(v).value
    left = (v << 8) & 0xFFFFFFFFFFFFFFFF
    # Arithmetic right shift (Python >> on signed int is arithmetic)
    right = ctypes.c_int64(v).value >> 55
    result = ((left ^ right) + c) & 0xFFFFFFFFFFFFFFFF
    return result


def hash_string_update(v: int, s: str) -> int:
    v = hash_update(v, len(s))
    for ch in s:
        v = hash_update(v, ord(ch))
    return v


def compute_struct_hash(struct: LcmStruct) -> int:
    v = 0x12345678
    for member in struct.members:
        v = hash_string_update(v, member.name)
        if is_primitive(member.type):
            v = hash_string_update(v, member.type)
        ndim = len(member.dimensions)
        v = hash_update(v, ndim)
        for dim in member.dimensions:
            mode = 0 if dim.is_constant else 1
            v = hash_update(v, mode)
            v = hash_string_update(v, dim.size)
    return v


# ── Rust Code Generation ────────────────────────────────────────────────────

RUST_KEYWORDS = {
    "as",
    "async",
    "await",
    "break",
    "const",
    "continue",
    "crate",
    "dyn",
    "else",
    "enum",
    "extern",
    "false",
    "fn",
    "for",
    "if",
    "impl",
    "in",
    "let",
    "loop",
    "match",
    "mod",
    "move",
    "mut",
    "pub",
    "ref",
    "return",
    "self",
    "Self",
    "static",
    "struct",
    "super",
    "trait",
    "true",
    "type",
    "unsafe",
    "use",
    "where",
    "while",
    "yield",
    "box",
}


def rust_field_name(name: str) -> str:
    """Escape Rust keywords with r# prefix."""
    if name in RUST_KEYWORDS:
        return f"r#{name}"
    return name


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def rust_type(lcm_type: str) -> str:
    """Map LCM primitive type to Rust type."""
    mapping = {
        "int8_t": "i8",
        "int16_t": "i16",
        "int32_t": "i32",
        "int64_t": "i64",
        "float": "f32",
        "double": "f64",
        "string": "std::string::String",
        "boolean": "bool",
        "byte": "u8",
    }
    return mapping.get(lcm_type, lcm_type)


def rust_const_type(lcm_type: str) -> str:
    """Map LCM type to Rust type for constants."""
    mapping = {
        "int8_t": "i8",
        "int16_t": "i16",
        "int32_t": "i32",
        "int64_t": "i64",
        "float": "f32",
        "double": "f64",
        "byte": "u8",
    }
    return mapping.get(lcm_type, lcm_type)


def primitive_size(lcm_type: str) -> int:
    sizes = {
        "int8_t": 1,
        "byte": 1,
        "boolean": 1,
        "int16_t": 2,
        "int32_t": 4,
        "float": 4,
        "int64_t": 8,
        "double": 8,
    }
    return sizes.get(lcm_type, 0)


def struct_ref_type(member_type: str, current_pkg: str) -> str:
    """Generate fully qualified Rust type path for a struct reference."""
    if "." in member_type:
        pkg, name = member_type.rsplit(".", 1)
        return f"crate::{pkg}::{name}"
    else:
        # Same package
        return f"crate::{current_pkg}::{member_type}"


def member_rust_type(member: LcmMember, current_pkg: str) -> str:
    """Get the full Rust type for a member including dimensions."""
    if is_primitive(member.type):
        base = rust_type(member.type)
    else:
        base = struct_ref_type(member.type, current_pkg)

    if not member.dimensions:
        return base

    # Build type from innermost outward
    result = base
    for dim in reversed(member.dimensions):
        if dim.is_constant:
            result = f"[{result}; {dim.size}]"
        else:
            result = f"Vec<{result}>"
    return result


def find_length_fields(struct: LcmStruct) -> set[str]:
    """Find member names that serve as length fields for variable-length arrays.
    These should be suppressed from the Rust struct."""
    length_fields = set()
    for member in struct.members:
        for dim in member.dimensions:
            if not dim.is_constant:
                length_fields.add(dim.size)
    return length_fields


def needs_manual_default(struct: LcmStruct, length_fields: set[str]) -> bool:
    """Check if struct needs a manual Default impl (arrays > 32 elements)."""
    for member in struct.members:
        if member.name in length_fields:
            continue
        for dim in member.dimensions:
            if dim.is_constant and int(dim.size) > 32:
                return True
    return False


# ── Code Generation Functions ────────────────────────────────────────────────


def gen_struct(struct: LcmStruct, all_structs: dict[str, LcmStruct]) -> str:
    """Generate complete Rust code for one LCM struct."""
    lines = []
    length_fields = find_length_fields(struct)
    manual_default = needs_manual_default(struct, length_fields)

    # Collect non-primitive dependencies for use statements
    deps = set()
    for member in struct.members:
        if not is_primitive(member.type) and member.name not in length_fields:
            deps.add(struct_ref_type(member.type, struct.package))

    lines.append("// Auto-generated by lcm-rust-gen. DO NOT EDIT.")
    lines.append("")
    lines.append("use byteorder::{BigEndian, ReadBytesExt, WriteBytesExt};")
    lines.append("use std::io::{self, Read, Write, Cursor};")
    lines.append("use std::sync::OnceLock;")
    lines.append("")

    # Derive list
    if manual_default:
        derives = "#[derive(Debug, Clone, PartialEq)]"
    else:
        derives = "#[derive(Debug, Clone, Default, PartialEq)]"

    lines.append(derives)
    lines.append(f"pub struct {struct.name} {{")

    # Constants as associated consts go in impl, members as fields
    for member in struct.members:
        if member.name in length_fields:
            continue
        field_type = member_rust_type(member, struct.package)
        fname = rust_field_name(member.name)
        lines.append(f"    pub {fname}: {field_type},")
    lines.append("}")
    lines.append("")

    # Manual Default impl if needed
    if manual_default:
        lines.append(f"impl Default for {struct.name} {{")
        lines.append("    fn default() -> Self {")
        lines.append("        Self {")
        for member in struct.members:
            if member.name in length_fields:
                continue
            fname = rust_field_name(member.name)
            default_val = gen_default_value(member, struct.package)
            lines.append(f"            {fname}: {default_val},")
        lines.append("        }")
        lines.append("    }")
        lines.append("}")
        lines.append("")

    # impl block
    lines.append(f"impl {struct.name} {{")

    # Base hash constant
    lines.append(f"    pub const HASH: i64 = 0x{struct.hash:016X}u64 as i64;")
    lines.append(f'    pub const NAME: &str = "{struct.full_name}";')
    lines.append("")

    # Constants
    for const in struct.constants:
        ct = rust_const_type(const.type)
        val = const.value
        cname = const.name
        lines.append(f"    pub const {cname}: {ct} = {val};")
    if struct.constants:
        lines.append("")

    # Fingerprint cache
    lines.append("    fn packed_fingerprint() -> u64 {")
    lines.append("        static CACHE: OnceLock<u64> = OnceLock::new();")
    lines.append("        *CACHE.get_or_init(|| Self::hash_recursive(&mut Vec::new()))")
    lines.append("    }")
    lines.append("")

    # hash_recursive
    gen_hash_recursive(lines, struct, all_structs)

    # encode
    gen_encode(lines, struct, length_fields)

    # decode
    gen_decode(lines, struct, length_fields, all_structs)

    # encode_one / decode_one
    gen_encode_one(lines, struct, length_fields, all_structs)
    gen_decode_one(lines, struct, length_fields, all_structs)

    # encoded_size
    gen_encoded_size(lines, struct, length_fields, all_structs)

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def gen_default_value(member: LcmMember, current_pkg: str) -> str:
    """Generate default value for a member."""
    if not member.dimensions:
        if is_primitive(member.type):
            if member.type == "string":
                return "std::string::String::new()"
            elif member.type == "boolean":
                return "false"
            else:
                return (
                    f"0{rust_type(member.type).replace('u8', '')}" if member.type == "byte" else "0"
                )
        else:
            ref_type = struct_ref_type(member.type, current_pkg)
            return f"{ref_type}::default()"

    # Check for variable-length (Vec)
    has_variable = any(not d.is_constant for d in member.dimensions)
    if has_variable:
        return "Vec::new()"

    # Fixed-size array
    return gen_fixed_array_default(member, current_pkg, 0)


def gen_fixed_array_default(member: LcmMember, current_pkg: str, dim_idx: int) -> str:
    if dim_idx >= len(member.dimensions):
        if is_primitive(member.type):
            if member.type == "string":
                return "std::string::String::new()"
            elif member.type == "boolean":
                return "false"
            else:
                t = rust_type(member.type)
                return f"0{t}" if t != "u8" else "0u8"
        else:
            ref_type = struct_ref_type(member.type, current_pkg)
            return f"{ref_type}::default()"

    dim = member.dimensions[dim_idx]
    size = int(dim.size)
    inner = gen_fixed_array_default(member, current_pkg, dim_idx + 1)

    if size > 32:
        # Can't use [val; N] for non-Copy types, but primitives are Copy
        return f"[{inner}; {size}]"
    else:
        return f"[{inner}; {size}]"


def gen_hash_recursive(lines: list[str], struct: LcmStruct, all_structs: dict[str, LcmStruct]):
    """Generate _get_hash_recursive equivalent."""
    length_fields = find_length_fields(struct)

    # Collect nested (non-primitive) types used in members
    nested_types = []
    for member in struct.members:
        if member.name in length_fields:
            continue
        if not is_primitive(member.type):
            nested_types.append(struct_ref_type(member.type, struct.package))

    lines.append("    pub(crate) fn hash_recursive(parents: &mut Vec<u64>) -> u64 {")
    lines.append("        let self_hash = Self::HASH as u64;")
    lines.append("        if parents.contains(&self_hash) {")
    lines.append("            return 0;")
    lines.append("        }")
    lines.append("        parents.push(self_hash);")

    if nested_types:
        lines.append("        let mut tmphash = self_hash as u64;")
        for nt in nested_types:
            lines.append(f"        tmphash = tmphash.wrapping_add({nt}::hash_recursive(parents));")
    else:
        lines.append("        let tmphash = self_hash as u64;")

    lines.append("        parents.pop();")
    lines.append("        // rotate left by 1")
    lines.append("        tmphash << 1 | tmphash >> 63")
    lines.append("    }")
    lines.append("")


def gen_encode(lines: list[str], struct: LcmStruct, length_fields: set[str]):
    lines.append("    pub fn encode(&self) -> Vec<u8> {")
    lines.append("        let mut buf = Vec::with_capacity(8 + self.encoded_size());")
    lines.append("        buf.write_u64::<BigEndian>(Self::packed_fingerprint()).unwrap();")
    lines.append("        self.encode_one(&mut buf).unwrap();")
    lines.append("        buf")
    lines.append("    }")
    lines.append("")


def gen_decode(
    lines: list[str], struct: LcmStruct, length_fields: set[str], all_structs: dict[str, LcmStruct]
):
    lines.append("    pub fn decode(data: &[u8]) -> io::Result<Self> {")
    lines.append("        let mut cursor = Cursor::new(data);")
    lines.append("        let hash = cursor.read_u64::<BigEndian>()?;")
    lines.append("        let expected = Self::packed_fingerprint();")
    lines.append("        if hash != expected {")
    lines.append("            return Err(io::Error::new(io::ErrorKind::InvalidData,")
    lines.append(
        '                format!("Hash mismatch: expected {:016x}, got {:016x}", expected, hash)));'
    )
    lines.append("        }")
    lines.append("        Self::decode_one(&mut cursor)")
    lines.append("    }")
    lines.append("")


def gen_encode_one(
    lines: list[str], struct: LcmStruct, length_fields: set[str], all_structs: dict[str, LcmStruct]
):
    [m for m in struct.members if m.name not in length_fields]
    has_members = bool(struct.members)
    buf_name = "buf" if has_members else "_buf"
    lines.append(f"    pub fn encode_one<W: Write>(&self, {buf_name}: &mut W) -> io::Result<()> {{")
    for member in struct.members:
        if member.name in length_fields:
            # Write the length from the corresponding Vec
            vec_member = find_vec_for_length(struct, member.name)
            if vec_member:
                fname = rust_field_name(vec_member.name)
                lines.append(f"        buf.write_i32::<BigEndian>(self.{fname}.len() as i32)?;")
            continue
        gen_encode_member(lines, member, struct.package, "self.", 2)
    lines.append("        Ok(())")
    lines.append("    }")
    lines.append("")


def find_vec_for_length(struct: LcmStruct, length_field_name: str) -> LcmMember | None:
    """Find the member whose variable-length dimension references this length field."""
    for member in struct.members:
        for dim in member.dimensions:
            if not dim.is_constant and dim.size == length_field_name:
                return member
    return None


def gen_encode_member(lines: list[str], member: LcmMember, pkg: str, prefix: str, indent: int):
    """Generate encode code for a single member."""
    "    " * indent
    fname = rust_field_name(member.name)
    accessor = f"{prefix}{fname}"

    if not member.dimensions:
        # Scalar
        gen_encode_primitive(lines, member.type, accessor, pkg, indent)
    else:
        gen_encode_array(lines, member, pkg, accessor, indent, 0)


def gen_encode_primitive(lines: list[str], lcm_type: str, source: str, pkg: str, indent: int):
    ind = "    " * indent
    if lcm_type == "int8_t":
        lines.append(f"{ind}buf.write_i8({source})?;")
    elif lcm_type == "byte":
        lines.append(f"{ind}buf.write_u8({source})?;")
    elif lcm_type == "boolean":
        lines.append(f"{ind}buf.write_i8(if {source} {{ 1 }} else {{ 0 }})?;")
    elif lcm_type == "int16_t":
        lines.append(f"{ind}buf.write_i16::<BigEndian>({source})?;")
    elif lcm_type == "int32_t":
        lines.append(f"{ind}buf.write_i32::<BigEndian>({source})?;")
    elif lcm_type == "int64_t":
        lines.append(f"{ind}buf.write_i64::<BigEndian>({source})?;")
    elif lcm_type == "float":
        lines.append(f"{ind}buf.write_f32::<BigEndian>({source})?;")
    elif lcm_type == "double":
        lines.append(f"{ind}buf.write_f64::<BigEndian>({source})?;")
    elif lcm_type == "string":
        lines.append(f"{ind}{{")
        lines.append(f"{ind}    let bytes = {source}.as_bytes();")
        lines.append(f"{ind}    buf.write_u32::<BigEndian>((bytes.len() + 1) as u32)?;")
        lines.append(f"{ind}    buf.write_all(bytes)?;")
        lines.append(f"{ind}    buf.write_u8(0)?;")
        lines.append(f"{ind}}}")
    else:
        # Nested struct
        lines.append(f"{ind}{source}.encode_one(buf)?;")


def gen_encode_array(
    lines: list[str], member: LcmMember, pkg: str, source: str, indent: int, dim_idx: int
):
    ind = "    " * indent
    dim = member.dimensions[dim_idx]
    is_last = dim_idx == len(member.dimensions) - 1
    loop_var = f"v{dim_idx}"

    if member.type == "byte" and is_last:
        # Byte array — write all at once
        if dim.is_constant:
            lines.append(f"{ind}buf.write_all(&{source})?;")
        else:
            lines.append(f"{ind}buf.write_all(&{source})?;")
        return

    lines.append(f"{ind}for {loop_var} in {source}.iter() {{")
    if is_last:
        # Use *v to deref
        deref = f"*{loop_var}"
        if is_primitive(member.type) and member.type != "string":
            gen_encode_primitive(lines, member.type, deref, pkg, indent + 1)
        elif member.type == "string":
            gen_encode_primitive(lines, member.type, loop_var, pkg, indent + 1)
        else:
            gen_encode_primitive(lines, member.type, loop_var, pkg, indent + 1)
    else:
        gen_encode_array(lines, member, pkg, loop_var, indent + 1, dim_idx + 1)
    lines.append(f"{ind}}}")


def gen_decode_one(
    lines: list[str], struct: LcmStruct, length_fields: set[str], all_structs: dict[str, LcmStruct]
):
    has_members = bool(struct.members)
    buf_name = "buf" if has_members else "_buf"
    lines.append(f"    pub fn decode_one<R: Read>({buf_name}: &mut R) -> io::Result<Self> {{")

    # First, read length fields into local vars
    # We need to handle the order correctly — members are in wire order
    for member in struct.members:
        if member.name in length_fields:
            lines.append(f"        let {member.name} = buf.read_i32::<BigEndian>()? as usize;")
        else:
            fname = rust_field_name(member.name)
            gen_decode_member(lines, member, struct.package, fname, 2, length_fields)

    # Construct result
    lines.append("        Ok(Self {")
    for member in struct.members:
        if member.name in length_fields:
            continue
        fname = rust_field_name(member.name)
        lines.append(f"            {fname},")
    lines.append("        })")
    lines.append("    }")
    lines.append("")


def gen_decode_member(
    lines: list[str],
    member: LcmMember,
    pkg: str,
    var_name: str,
    indent: int,
    length_fields: set[str],
):
    "    " * indent

    if not member.dimensions:
        gen_decode_primitive(lines, member.type, var_name, pkg, indent)
    else:
        gen_decode_array(lines, member, pkg, var_name, indent, 0, length_fields)


def gen_decode_primitive(lines: list[str], lcm_type: str, var_name: str, pkg: str, indent: int):
    ind = "    " * indent
    if lcm_type == "int8_t":
        lines.append(f"{ind}let {var_name} = buf.read_i8()?;")
    elif lcm_type == "byte":
        lines.append(f"{ind}let {var_name} = buf.read_u8()?;")
    elif lcm_type == "boolean":
        lines.append(f"{ind}let {var_name} = buf.read_i8()? != 0;")
    elif lcm_type == "int16_t":
        lines.append(f"{ind}let {var_name} = buf.read_i16::<BigEndian>()?;")
    elif lcm_type == "int32_t":
        lines.append(f"{ind}let {var_name} = buf.read_i32::<BigEndian>()?;")
    elif lcm_type == "int64_t":
        lines.append(f"{ind}let {var_name} = buf.read_i64::<BigEndian>()?;")
    elif lcm_type == "float":
        lines.append(f"{ind}let {var_name} = buf.read_f32::<BigEndian>()?;")
    elif lcm_type == "double":
        lines.append(f"{ind}let {var_name} = buf.read_f64::<BigEndian>()?;")
    elif lcm_type == "string":
        lines.append(f"{ind}let {var_name} = {{")
        lines.append(f"{ind}    let len = buf.read_u32::<BigEndian>()? as usize;")
        lines.append(f"{ind}    let mut bytes = vec![0u8; len];")
        lines.append(f"{ind}    buf.read_exact(&mut bytes)?;")
        lines.append(f"{ind}    std::string::String::from_utf8(bytes[..len - 1].to_vec())")
        lines.append(f"{ind}        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?")
        lines.append(f"{ind}}};")
    else:
        # Nested struct
        ref_type = struct_ref_type(lcm_type, pkg)
        lines.append(f"{ind}let {var_name} = {ref_type}::decode_one(buf)?;")


def gen_decode_array(
    lines: list[str],
    member: LcmMember,
    pkg: str,
    var_name: str,
    indent: int,
    dim_idx: int,
    length_fields: set[str],
):
    ind = "    " * indent
    dim = member.dimensions[dim_idx]
    is_last = dim_idx == len(member.dimensions) - 1

    if dim.is_constant:
        size = dim.size
    else:
        size = dim.size  # This is the name of the length field (local variable)

    if member.type == "byte" and is_last:
        # Byte array — read all at once
        if dim.is_constant:
            lines.append(f"{ind}let {var_name} = {{")
            lines.append(f"{ind}    let mut arr = [0u8; {size}];")
            lines.append(f"{ind}    buf.read_exact(&mut arr)?;")
            lines.append(f"{ind}    arr")
            lines.append(f"{ind}}};")
        else:
            lines.append(f"{ind}let {var_name} = {{")
            lines.append(f"{ind}    let mut v = vec![0u8; {size}];")
            lines.append(f"{ind}    buf.read_exact(&mut v)?;")
            lines.append(f"{ind}    v")
            lines.append(f"{ind}}};")
        return

    if dim.is_constant:
        # Fixed-size array — use array initialization
        int(size)
        lines.append(f"{ind}let {var_name} = {{")
        inner_var = f"_arr_{dim_idx}"

        if is_last and is_primitive(member.type) and member.type != "string":
            # Read each element for fixed-size primitive array
            rust_type(member.type)
            lines.append(
                f"{ind}    let mut {inner_var} = [{gen_primitive_zero(member.type)}; {size}];"
            )
            lines.append(f"{ind}    for elem in {inner_var}.iter_mut() {{")
            gen_decode_primitive_assign(lines, member.type, "elem", indent + 2)
            lines.append(f"{ind}    }}")
            lines.append(f"{ind}    {inner_var}")
        elif is_last:
            # Non-primitive or string array
            lines.append(f"{ind}    let mut {inner_var} = Vec::with_capacity({size});")
            lines.append(f"{ind}    for _ in 0..{size} {{")
            elem_var = f"_elem_{dim_idx}"
            gen_decode_primitive(lines, member.type, elem_var, pkg, indent + 2)
            lines.append(f"{ind}        {inner_var}.push({elem_var});")
            lines.append(f"{ind}    }}")
            # Convert Vec to array — use try_into for correctness
            lines.append(f"{ind}    <[_; {size}]>::try_from({inner_var}).unwrap()")
        else:
            # Multi-dimensional — recurse
            lines.append(f"{ind}    let mut {inner_var} = Vec::with_capacity({size});")
            lines.append(f"{ind}    for _ in 0..{size} {{")
            elem_var = f"_elem_{dim_idx}"
            gen_decode_array(lines, member, pkg, elem_var, indent + 2, dim_idx + 1, length_fields)
            lines.append(f"{ind}        {inner_var}.push({elem_var});")
            lines.append(f"{ind}    }}")
            lines.append(f"{ind}    <[_; {size}]>::try_from({inner_var}).unwrap()")
        lines.append(f"{ind}}};")
    else:
        # Variable-size — Vec
        lines.append(f"{ind}let {var_name} = {{")
        lines.append(f"{ind}    let mut v = Vec::with_capacity({size});")
        lines.append(f"{ind}    for _ in 0..{size} {{")
        if is_last:
            elem_var = f"_elem_{dim_idx}"
            gen_decode_primitive(lines, member.type, elem_var, pkg, indent + 2)
            lines.append(f"{ind}        v.push({elem_var});")
        else:
            elem_var = f"_elem_{dim_idx}"
            gen_decode_array(lines, member, pkg, elem_var, indent + 2, dim_idx + 1, length_fields)
            lines.append(f"{ind}        v.push({elem_var});")
        lines.append(f"{ind}    }}")
        lines.append(f"{ind}    v")
        lines.append(f"{ind}}};")


def gen_decode_primitive_assign(lines: list[str], lcm_type: str, target: str, indent: int):
    """Decode a primitive and assign to an existing mutable variable."""
    ind = "    " * indent
    if lcm_type == "int8_t":
        lines.append(f"{ind}*{target} = buf.read_i8()?;")
    elif lcm_type == "byte":
        lines.append(f"{ind}*{target} = buf.read_u8()?;")
    elif lcm_type == "boolean":
        lines.append(f"{ind}*{target} = buf.read_i8()? != 0;")
    elif lcm_type == "int16_t":
        lines.append(f"{ind}*{target} = buf.read_i16::<BigEndian>()?;")
    elif lcm_type == "int32_t":
        lines.append(f"{ind}*{target} = buf.read_i32::<BigEndian>()?;")
    elif lcm_type == "int64_t":
        lines.append(f"{ind}*{target} = buf.read_i64::<BigEndian>()?;")
    elif lcm_type == "float":
        lines.append(f"{ind}*{target} = buf.read_f32::<BigEndian>()?;")
    elif lcm_type == "double":
        lines.append(f"{ind}*{target} = buf.read_f64::<BigEndian>()?;")


def gen_primitive_zero(lcm_type: str) -> str:
    mapping = {
        "int8_t": "0i8",
        "int16_t": "0i16",
        "int32_t": "0i32",
        "int64_t": "0i64",
        "float": "0.0f32",
        "double": "0.0f64",
        "byte": "0u8",
        "boolean": "false",
    }
    return mapping.get(lcm_type, "Default::default()")


def gen_encoded_size(
    lines: list[str], struct: LcmStruct, length_fields: set[str], all_structs: dict[str, LcmStruct]
):
    lines.append("    pub fn encoded_size(&self) -> usize {")
    has_members = bool(struct.members)
    if has_members:
        lines.append("        let mut size = 0usize;")

    for member in struct.members:
        if member.name in length_fields:
            # Length field itself is i32 = 4 bytes
            lines.append("        size += 4;")
            continue
        gen_encoded_size_member(lines, member, struct.package, "self.", 2)

    if has_members:
        lines.append("        size")
    else:
        lines.append("        0")
    lines.append("    }")
    lines.append("")


def gen_encoded_size_member(
    lines: list[str], member: LcmMember, pkg: str, prefix: str, indent: int
):
    ind = "    " * indent
    fname = rust_field_name(member.name)
    accessor = f"{prefix}{fname}"

    if not member.dimensions:
        if is_primitive(member.type):
            if member.type == "string":
                lines.append(f"{ind}size += 4 + {accessor}.len() + 1;")
            else:
                lines.append(f"{ind}size += {primitive_size(member.type)};")
        else:
            lines.append(f"{ind}size += {accessor}.encoded_size();")
    else:
        gen_encoded_size_array(lines, member, pkg, accessor, indent, 0)


def gen_encoded_size_array(
    lines: list[str], member: LcmMember, pkg: str, source: str, indent: int, dim_idx: int
):
    ind = "    " * indent
    member.dimensions[dim_idx]
    is_last = dim_idx == len(member.dimensions) - 1

    if is_last:
        if is_primitive(member.type):
            if member.type == "string":
                loop_var = f"s{dim_idx}"
                lines.append(f"{ind}for {loop_var} in {source}.iter() {{")
                lines.append(f"{ind}    size += 4 + {loop_var}.len() + 1;")
                lines.append(f"{ind}}}")
            elif member.type == "byte":
                lines.append(f"{ind}size += {source}.len();")
            else:
                lines.append(f"{ind}size += {source}.len() * {primitive_size(member.type)};")
        else:
            loop_var = f"v{dim_idx}"
            lines.append(f"{ind}for {loop_var} in {source}.iter() {{")
            lines.append(f"{ind}    size += {loop_var}.encoded_size();")
            lines.append(f"{ind}}}")
    else:
        loop_var = f"v{dim_idx}"
        lines.append(f"{ind}for {loop_var} in {source}.iter() {{")
        gen_encoded_size_array(lines, member, pkg, loop_var, indent + 1, dim_idx + 1)
        lines.append(f"{ind}}}")


# ── Crate Generation ─────────────────────────────────────────────────────────


def generate_crate(lcm_dir: str, out_dir: str):
    """Parse all .lcm files and generate a complete Rust crate."""
    lcm_files = sorted(Path(lcm_dir).glob("*.lcm"))
    if not lcm_files:
        print(f"No .lcm files found in {lcm_dir}", file=sys.stderr)
        sys.exit(1)

    # Parse all files
    parsed: list[LcmFile] = []
    all_structs: dict[str, LcmStruct] = {}
    for path in lcm_files:
        f = parse_file(str(path))
        parsed.append(f)
        for s in f.structs:
            all_structs[s.full_name] = s

    # Group by package
    packages: dict[str, list[LcmStruct]] = {}
    for f in parsed:
        for s in f.structs:
            packages.setdefault(s.package, []).append(s)

    # Create output structure
    src_dir = Path(out_dir) / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # Generate Cargo.toml
    cargo_toml = Path(out_dir) / "Cargo.toml"
    cargo_toml.write_text(
        "[package]\n"
        'name = "lcm-msgs"\n'
        'version = "0.1.0"\n'
        'edition = "2021"\n'
        'description = "Auto-generated LCM message types for Rust"\n'
        "\n"
        "[dependencies]\n"
        'byteorder = "1"\n'
    )

    # Generate per-package modules
    for pkg, structs in sorted(packages.items()):
        pkg_dir = src_dir / pkg
        pkg_dir.mkdir(parents=True, exist_ok=True)

        # Generate each struct file
        type_names = []
        for s in sorted(structs, key=lambda s: s.name):
            snake_name = to_snake_case(s.name)
            type_names.append((snake_name, s.name))
            file_path = pkg_dir / f"{snake_name}.rs"
            code = gen_struct(s, all_structs)
            file_path.write_text(code)

        # Generate package mod.rs
        mod_lines = ["// Auto-generated by lcm-rust-gen. DO NOT EDIT.", ""]
        for snake_name, struct_name in sorted(type_names):
            mod_lines.append(f"mod {snake_name};")
            mod_lines.append(f"pub use {snake_name}::{struct_name};")
            mod_lines.append("")
        (pkg_dir / "mod.rs").write_text("\n".join(mod_lines))

    # Generate src/lib.rs
    lib_lines = [
        "// Auto-generated by lcm-rust-gen. DO NOT EDIT.",
        "#![allow(non_snake_case)]",
        "",
    ]
    for pkg in sorted(packages.keys()):
        lib_lines.append(f"pub mod {pkg};")
    lib_lines.append("")
    (src_dir / "lib.rs").write_text("\n".join(lib_lines))

    print(f"Generated {sum(len(v) for v in packages.values())} types in {len(packages)} packages")


def main():
    parser = argparse.ArgumentParser(description="LCM Rust Code Generator")
    parser.add_argument("lcm_dir", help="Directory containing .lcm files")
    parser.add_argument("-o", "--output", required=True, help="Output crate directory")
    args = parser.parse_args()
    generate_crate(args.lcm_dir, args.output)


if __name__ == "__main__":
    main()
