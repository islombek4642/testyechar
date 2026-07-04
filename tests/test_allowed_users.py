import json

from bot.allowed_users import AllowedUsersStore


def test_seeds_from_env_value_on_first_run(tmp_path):
    path = tmp_path / "allowed_users.json"
    store = AllowedUsersStore(admin_id=1, path=path, seed=[111, 222])
    assert store.list_ids() == [111, 222]
    assert path.exists()


def test_admin_always_allowed_even_if_not_listed(tmp_path):
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed_users.json")
    assert store.is_allowed(1)
    assert not store.is_allowed(999)


def test_add_persists_and_returns_true_when_new(tmp_path):
    path = tmp_path / "allowed_users.json"
    store = AllowedUsersStore(admin_id=1, path=path)
    assert store.add(555) is True
    assert store.is_allowed(555)
    assert json.loads(path.read_text(encoding="utf-8")) == [555]


def test_add_returns_false_for_duplicate_or_admin(tmp_path):
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed_users.json", seed=[555])
    assert store.add(555) is False
    assert store.add(1) is False  # admin is implicitly allowed, not addable


def test_remove_persists_and_returns_true_when_present(tmp_path):
    path = tmp_path / "allowed_users.json"
    store = AllowedUsersStore(admin_id=1, path=path, seed=[555])
    assert store.remove(555) is True
    assert not store.is_allowed(555)
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_remove_returns_false_when_absent(tmp_path):
    store = AllowedUsersStore(admin_id=1, path=tmp_path / "allowed_users.json")
    assert store.remove(555) is False


def test_state_survives_across_instances_pointed_at_same_file(tmp_path):
    path = tmp_path / "allowed_users.json"
    first = AllowedUsersStore(admin_id=1, path=path, seed=[111])
    first.add(222)

    second = AllowedUsersStore(admin_id=1, path=path, seed=[999])  # seed ignored, file already exists
    assert second.list_ids() == [111, 222]


def test_corrupt_file_falls_back_to_seed(tmp_path):
    path = tmp_path / "allowed_users.json"
    path.write_text("not valid json", encoding="utf-8")
    store = AllowedUsersStore(admin_id=1, path=path, seed=[42])
    assert store.list_ids() == [42]
