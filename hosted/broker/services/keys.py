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

from datetime import datetime, timezone
import hashlib
import secrets

from models.api_key import APIKey
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

# Key format: dtk_live_<40 random hex chars> = 49 chars total
KEY_PREFIX_LIVE = "dtk_live_"
KEY_PREFIX_DEV = "dtk_dev_"

# Only update last_used_at if older than this (avoid write-per-request on SQLite)
LAST_USED_THROTTLE_SECONDS = 60


def generate_api_key(environment: str = "live") -> str:
    """Returns plaintext, shown to the user once."""
    prefix = KEY_PREFIX_LIVE if environment == "live" else KEY_PREFIX_DEV
    random_part = secrets.token_hex(20)
    return f"{prefix}{random_part}"


def hash_key(plaintext_key: str) -> str:
    # SHA-256 intentional: keys are 160-bit random tokens (not passwords) needing O(1) lookup.
    return hashlib.sha256(plaintext_key.encode()).hexdigest()


def get_key_prefix(plaintext_key: str) -> str:
    return plaintext_key[:14]


async def create_api_key(
    db: AsyncSession,
    owner_id: str,
    name: str,
    robot_id: str | None = None,
    environment: str = "live",
) -> tuple[APIKey, str]:
    """Returns (db record, plaintext key).

    The plaintext key is returned ONCE and never stored.
    Robot IDs are namespaced to the owner to prevent cross-tenant collisions.
    """
    plaintext = generate_api_key(environment)

    namespaced_robot_id = f"{owner_id}:{robot_id}" if robot_id else None

    key_record = APIKey(
        key_prefix=get_key_prefix(plaintext),
        key_hash=hash_key(plaintext),
        name=name,
        owner_id=owner_id,
        robot_id=namespaced_robot_id,
    )
    db.add(key_record)
    await db.commit()
    await db.refresh(key_record)
    return key_record, plaintext


async def validate_api_key(db: AsyncSession, plaintext_key: str) -> APIKey | None:
    hashed = hash_key(plaintext_key)
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == hashed, APIKey.revoked == False)  # noqa: E712
    )
    key_record = result.scalar_one_or_none()
    if key_record:
        # SQLite has no native timezone support, so the column comes back
        # tz-naive even though we wrote tz-aware. Normalize to UTC before
        # subtracting; otherwise this raises TypeError on every call after
        # the first.
        now = datetime.now(timezone.utc)
        last_used = key_record.last_used_at
        if last_used is not None and last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=timezone.utc)
        if last_used is None or (now - last_used).total_seconds() > LAST_USED_THROTTLE_SECONDS:
            await db.execute(
                update(APIKey).where(APIKey.id == key_record.id).values(last_used_at=now)
            )
            await db.commit()
    return key_record


async def list_api_keys(db: AsyncSession, owner_id: str) -> list[APIKey]:
    result = await db.execute(
        select(APIKey)
        .where(APIKey.owner_id == owner_id, APIKey.revoked == False)  # noqa: E712
        .order_by(APIKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(db: AsyncSession, key_id: str, owner_id: str) -> bool:
    result = await db.execute(
        update(APIKey)
        .where(APIKey.id == key_id, APIKey.owner_id == owner_id, APIKey.revoked == False)  # noqa: E712
        .values(revoked=True)
    )
    await db.commit()
    return result.rowcount > 0
