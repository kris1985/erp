from app.services.lifecycle_agents import allowed_metric_ids, select_profiles


def test_cross_lifecycle_question_selects_relevant_registered_profiles():
    profiles = select_profiles("这张急单缺料又会不会挤占针车产能，能不能接？")
    ids = {profile.id for profile in profiles}
    assert {"order_commitment", "procurement_supply", "schedule_capacity"} <= ids
    assert "analytics.order_intake" in (allowed_metric_ids(profiles) or set())
    assert "materials.shortages" in (allowed_metric_ids(profiles) or set())


def test_unclassified_question_does_not_expand_or_hide_catalog():
    assert select_profiles("你好") == []
    assert allowed_metric_ids([]) is None
