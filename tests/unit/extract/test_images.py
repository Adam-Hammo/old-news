import pytest

from old_news.extract.images import carries

SUBSTACK = "https://substackcdn.com/image/fetch/$s_!Udbx!,{}/https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2F720ae9b4_732x486.png"


@pytest.mark.parametrize(
    ("lead", "shown"),
    [
        (SUBSTACK.format("w_1200,h_675,c_fill"), SUBSTACK.format("w_1456,c_limit")),
        (
            "https://assets.example.com/dims4/crop/337x190/?url=https%3A%2F%2Fbucket.example.com%2F09%2Fgetty-2249057833.jpg",
            "https://assets.example.com/09/67/getty-2249057833.jpg?imwidth=1280",
        ),
        (
            "https://imgs.example.com/comics/ground_effect_2x.png",
            "https://imgs.example.com/comics/ground_effect.png",
        ),
        (
            "http://example.org/wp-content/uploads/2026/07/by_group-scaled.png",
            "https://example.org/wp-content/uploads/2026/07/by_group-1440x780.png",
        ),
        (
            "https://example.io/content/images/size/w1200/2026/10/chart.png",
            "https://example.io/content/images/2026/10/chart.png",
        ),
    ],
)
def test_a_lead_is_found_in_another_rendition(lead, shown):
    assert carries(f"Text.\n\n![]({shown})\n\nMore.", lead)


@pytest.mark.parametrize(
    ("lead", "shown"),
    [
        (
            "https://example.io/content/images/2026/10/image2.png",
            "https://example.io/content/images/2026/10/image2-1.png",
        ),
        (
            "https://cdn.example.net/1b1e6d534c?crop=1527",
            "https://cdn.example.net/aeabf43746?crop=2000",
        ),
        (
            "https://badges.example.net/image.php?id=8467",
            "https://badges.example.net/image.php?id=9407",
        ),
    ],
)
def test_a_different_picture_is_not_the_lead(lead, shown):
    assert not carries(f"![]({shown})", lead)
