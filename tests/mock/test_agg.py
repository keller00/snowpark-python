#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#

import math
from typing import List

import pytest

import snowflake.snowpark.mock.mock_functions as snowpark_mock_functions
from snowflake.snowpark import DataFrame, Row, Session
from snowflake.snowpark.functions import (
    approx_percentile,
    approx_percentile_combine,
    array_agg,
    avg,
    col,
    count,
    covar_pop,
    covar_samp,
    grouping,
    listagg,
    max,
    mean,
    median,
    min,
    stddev,
    stddev_pop,
    sum,
)
from snowflake.snowpark.mock.mock_connection import MockServerConnection
from snowflake.snowpark.mock.snowflake_data_type import ColumnEmulator
from tests.utils import Utils

session = Session(MockServerConnection())


def test_agg_single_column():
    origin_df: DataFrame = session.create_dataframe(
        [[1], [8], [6], [3], [100], [400], [None]], schema=["v"]
    )
    assert origin_df.select(sum("v")).collect() == [Row(518)]
    assert origin_df.select(max("v")).collect() == [Row(400)]
    assert origin_df.select(min("v")).collect() == [Row(1)]
    assert origin_df.select(median("v")).collect() == [Row(7.0)]
    assert origin_df.select(avg("v")).collect() == [
        Row(86.33333)
    ]  # snowflake keeps scale of 5
    assert origin_df.select(mean("v")).collect() == [Row(86.33333)]
    assert origin_df.select(count("v")).collect() == [Row(6)]


def test_agg_double_column():
    origin_df: DataFrame = session.create_dataframe(
        [
            [10.0, 11.0],
            [20.0, 22.0],
            [25.0, 0.0],
            [30.0, 35.0],
            [999.0, None],
            [None, 1234.0],
            [math.nan, None],
            [math.nan, 1.0],
        ],
        schema=["m", "n"],
    )
    assert origin_df.select(covar_pop("m", "n")).collect() == [Row(38.75)]
    assert origin_df.select(sum(col("m") + col("n"))).collect() == [Row(153.0)]
    assert origin_df.select(sum(col("m") - col("n"))).collect() == [Row(17.0)]


def test_agg_function_multiple_parameters():
    origin_df: DataFrame = session.create_dataframe(
        ["k1", "k1", "k3", "k4", [None]], schema=["v"]
    )
    assert origin_df.select(listagg("v", delimiter='~!1,."')).collect() == [
        Row('k1~!1,."k1~!1,."k3~!1,."k4')
    ]

    assert origin_df.select(
        listagg("v", delimiter='~!1,."', is_distinct=True)
    ).collect() == [Row('k1~!1,."k3~!1,."k4')]


def test_register_new_methods():
    origin_df: DataFrame = session.create_dataframe(
        [
            [10.0, 11.0],
            [20.0, 22.0],
            [25.0, 0.0],
            [30.0, 35.0],
        ],
        schema=["m", "n"],
    )

    # approx_percentile
    with pytest.raises(NotImplementedError):
        origin_df.select(approx_percentile(col("m"), 0.5)).collect()

    def mock_approx_percentile(
        columns: List[ColumnEmulator], **kwargs
    ) -> ColumnEmulator:
        assert len(columns) == 1
        assert columns[0].tolist() == [10.0, 20.0, 25.0, 30.0]
        assert kwargs.pop("percentile") == 0.5
        assert not kwargs
        return ColumnEmulator(data=123)

    snowpark_mock_functions.register_func_implementation(
        "approx_percentile", mock_approx_percentile
    )
    assert origin_df.select(approx_percentile(col("m"), 0.5)).collect() == [Row(123)]

    # covar_samp
    with pytest.raises(NotImplementedError):
        origin_df.select(covar_samp(col("m"), "n")).collect()

    def mock_mock_samp(columns: List[ColumnEmulator], **kwargs):
        assert len(columns) == 2
        assert columns[0].tolist() == [10.0, 20.0, 25.0, 30.0]
        assert columns[1].tolist() == [11.0, 22.0, 0.0, 35.0]
        assert not kwargs
        return ColumnEmulator(data=123)

    snowpark_mock_functions.register_func_implementation("covar_samp", mock_mock_samp)
    assert origin_df.select(covar_samp(col("m"), "n")).collect() == [Row(123)]

    # stddev
    with pytest.raises(NotImplementedError):
        origin_df.select(stddev("n")).collect()

    def mock_stddev(columns: List[ColumnEmulator], **kwargs):
        assert len(columns) == 1
        assert columns[0].tolist() == [11.0, 22.0, 0.0, 35.0]
        assert not kwargs
        return ColumnEmulator(data=123)

    snowpark_mock_functions.register_func_implementation("stddev", mock_stddev)
    assert origin_df.select(stddev("n")).collect() == [Row(123)]

    # array_agg
    with pytest.raises(NotImplementedError):
        origin_df.select(array_agg("n", False)).collect()

    # instead of kwargs, positional argument also works
    def mock_mock_array_agg(columns: List[ColumnEmulator], is_distinct):
        assert is_distinct is True
        assert len(columns) == 1
        assert columns[0].tolist() == [11.0, 22.0, 0.0, 35.0]
        return ColumnEmulator(data=123)

    snowpark_mock_functions.register_func_implementation(
        "array_agg", mock_mock_array_agg
    )
    assert origin_df.select(array_agg("n", True)).collect() == [Row(123)]

    # grouping
    with pytest.raises(NotImplementedError):
        origin_df.select(grouping("m", col("n"))).collect()

    def mock_mock_grouping(columns: List[ColumnEmulator]):
        assert len(columns) == 2
        assert columns[0].tolist() == [10.0, 20.0, 25.0, 30.0]
        assert columns[1].tolist() == [11.0, 22.0, 0.0, 35.0]
        return ColumnEmulator(data=123)

    snowpark_mock_functions.register_func_implementation("grouping", mock_mock_grouping)
    assert origin_df.select(grouping("m", col("n"))).collect() == [Row(123)]


def test_group_by():
    origin_df: DataFrame = session.create_dataframe(
        [
            ["a", "ddd", 11.0],
            ["a", "ddd", 22.0],
            ["b", "ccc", 9.0],
            ["b", "ccc", 9.0],
            ["b", "aaa", 35.0],
            ["b", "aaa", 99.0],
        ],
        schema=["m", "n", "q"],
    )

    Utils.check_answer(
        origin_df.group_by("m").agg(sum("q")).collect(),
        [
            Row("a", 33.0),
            Row("b", 152.0),
        ],
    )

    Utils.check_answer(
        origin_df.group_by("n").agg(min("q")).collect(),
        [
            Row("ddd", 11.0),
            Row("ccc", 9.0),
            Row("aaa", 35.0),
        ],
    )

    with pytest.raises(NotImplementedError):
        origin_df.group_by("n", "m").agg(approx_percentile_combine("q")).collect()

    def mock_approx_percentile_combine(state: List[ColumnEmulator]):
        if state[0].iat[0] == 11:
            return ColumnEmulator(data=-1.0)
        if state[0].iat[0] == 9:
            return ColumnEmulator(data=0.0)
        if state[0].iat[0] == 35:
            return ColumnEmulator(data=1.0)
        raise RuntimeError("This error shall never be raised")

    snowpark_mock_functions.register_func_implementation(
        "approx_percentile_combine", mock_approx_percentile_combine
    )
    Utils.check_answer(
        origin_df.group_by("n").agg(approx_percentile_combine("q")).collect(),
        [
            Row("ddd", -1.0),
            Row("ccc", 0.0),
            Row("aaa", 1.0),
        ],
    )

    Utils.check_answer(
        origin_df.group_by("m", "n").agg(mean("q")).collect(),
        [
            Row("a", "ddd", 16.5),
            Row("b", "ccc", 9.0),
            Row("b", "aaa", 67.0),
        ],
    )


def test_agg():
    origin_df: DataFrame = session.create_dataframe(
        [
            [15.0, 11.0],
            [2.0, 22.0],
            [29.0, 9.0],
            [30.0, 9.0],
            [4.0, 35.0],
            [54.0, 99.0],
        ],
        schema=["m", "n"],
    )

    Utils.check_answer(origin_df.agg(sum("m")).collect(), Row(134.0))

    Utils.check_answer(origin_df.agg(min("m"), max("n")).collect(), Row(2.0, 99.0))

    Utils.check_answer(
        origin_df.agg({"m": "count", "n": "sum"}).collect(), Row(6.0, 185.0)
    )

    with pytest.raises(NotImplementedError):
        origin_df.select(stddev("n"), stddev_pop("m")).collect()

    def mock_stddev(columns: List[ColumnEmulator], **kwargs):
        assert len(columns) == 1
        assert columns[0].tolist() == [11.0, 22.0, 9.0, 9.0, 35.0, 99.0]
        assert not kwargs
        return ColumnEmulator(data=123)

    def mock_stddev_pop(columns: List[ColumnEmulator], **kwargs):
        assert len(columns) == 1
        assert columns[0].tolist() == [15.0, 2.0, 29.0, 30.0, 4.0, 54.0]
        assert not kwargs
        return ColumnEmulator(data=456)

    snowpark_mock_functions.register_func_implementation("stddev", mock_stddev)

    # stddev_pop is not implemented yet
    with pytest.raises(NotImplementedError):
        origin_df.select(stddev("n"), stddev_pop("m")).collect()

    snowpark_mock_functions.register_func_implementation("stddev_pop", mock_stddev_pop)

    Utils.check_answer(
        origin_df.select(stddev("n"), stddev_pop("m")).collect(), Row(123.0, 456.0)
    )