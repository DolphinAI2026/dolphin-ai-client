from uuid import UUID

from app.models.tenant import Tenant
from app.tenant_public_id import historical_tenant_public_id, new_tenant_public_id


def test_new_tenant_public_id_is_uuid4():
    value = new_tenant_public_id()

    parsed = UUID(value)

    assert parsed.version == 4
    assert value == str(parsed)


def test_historical_tenant_public_id_is_stable_uuid5():
    assert historical_tenant_public_id(42) == historical_tenant_public_id(42)
    assert UUID(historical_tenant_public_id(42)).version == 5


def test_tenant_public_id_column_is_nullable_unique_indexed_uuid_default():
    column = Tenant.__table__.c.public_id

    assert column.type.length == 36
    assert column.nullable is True
    assert column.unique is True
    assert column.index is True
    assert UUID(column.default.arg(None)).version == 4
