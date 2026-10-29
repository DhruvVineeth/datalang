"""Independent closed-form benchmark checks; these are not performance results."""

import pytest

from benchmarks.run_benchmark import expected_result, generate


@pytest.mark.parametrize("rows,z,null_key,b,selected", [
    (9, 8, 6, -2, 7), (10, 17.5, 6, -2, 8), (12, 16, 6, -2, 9),
    (13, 16, 10, -2, 10), (16, 16, 12, -2, 13), (17, 16, 12, -4, 14),
    (1_000, 897.5, 666, -222, 778), (10_000, 8897.5, 6666, -2222, 7778),
    (100_000, 88897.5, 66666, -22222, 77778),
])
def test_closed_form_oracle_matches_hand_calculations(rows, z, null_key, b, selected):
    assert expected_result(rows) == ((("z", z), (None, null_key), ("b", b), ("a", None)), selected)


def test_generated_bytes_are_deterministic_and_include_missing_values(tmp_path):
    path = tmp_path / "data.csv"
    generate(path, 10)
    expected = ("row,group_key,amount,units\n1,z,9.5,2\n2,a,,0\n3,z,-1.5,3\n4,,4.0,1\n"
                "5,a,,4\n6,b,0.0,2\n7,,2.0,1\n8,b,-2.0,2\n9,c,8.0,0\n10,z,9.5,2\n")
    assert path.read_bytes() == expected.encode("utf-8")
    generate(path, 10)
    assert path.read_bytes() == expected.encode("utf-8")


def test_generator_and_oracle_reject_incomplete_base_pattern(tmp_path):
    with pytest.raises(ValueError, match="nine rows"):
        generate(tmp_path / "data.csv", 8)
    with pytest.raises(ValueError, match="nine rows"):
        expected_result(8)
