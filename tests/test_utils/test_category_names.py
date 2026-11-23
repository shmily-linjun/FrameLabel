from anylabeling.views.labeling.utils.category_names import (
    parse_category_names,
)


def test_parse_category_names_supports_commas_spaces_newlines():
    assert parse_category_names("cat, dog，猫\n狗  cat") == [
        "cat",
        "dog",
        "猫",
        "狗",
    ]


def test_parse_category_names_ignores_empty_input():
    assert parse_category_names(" ,，\n\t ") == []
