from app.models import ProjectArtifactDependency


def test_model_columns_exist():
    cols = set(ProjectArtifactDependency.__table__.columns.keys())
    assert {"id", "project_id", "from_ref", "to_ref",
            "expose_label", "consume_label", "note", "created_at"} <= cols


def test_table_name():
    assert ProjectArtifactDependency.__tablename__ == "project_artifact_dependencies"
