import pytest

from old_news.passwords import hash_password, verify


def test_round_trip():
    assert verify("correct horse", hash_password("correct horse"))


def test_a_wrong_password_is_rejected():
    assert not verify("Correct Horse", hash_password("correct horse"))


def test_the_same_password_hashes_differently_every_time():
    """Distinct salts, so identical passwords aren't identifiable from the hashes."""
    assert hash_password("same") != hash_password("same")


def test_the_hash_never_contains_the_password():
    assert "hunter2" not in hash_password("hunter2")


def test_parameters_are_read_back_from_the_stored_hash():
    """Raising the cost later must not invalidate hashes made before it."""
    encoded = hash_password("stable")
    scheme, cost, block, parallel, _salt, _key = encoded.split(":")

    assert scheme == "scrypt"
    assert (int(cost), int(block), int(parallel)) == (2**15, 8, 1)
    assert verify("stable", encoded)


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "not-a-hash",
        "scrypt:32768:8:1:onlyfivefields",
        "bcrypt:32768:8:1:c2FsdA==:a2V5",
        "scrypt:abc:8:1:c2FsdA==:a2V5",
        "scrypt:32768:8:1:!!!notbase64!!!:a2V5",
        "scrypt:3:8:1:c2FsdA==:a2V5",
    ],
)
def test_malformed_hashes_are_rejected_rather_than_raising(encoded: str):
    """A corrupted env var must fail the login, not crash the request."""
    assert verify("anything", encoded) is False


def test_the_hash_survives_docker_compose_variable_substitution():
    """A `$` in the value gets expanded away by compose, destroying the salt."""
    assert "$" not in hash_password("anything")
