#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2021 Snowflake Computing Inc. All right reserved.
#

import pytest

from snowflake.snowpark.row import Row

from snowflake.snowpark.snowpark_client_exception import SnowparkClientException


def test_column_constructors_subscriptable(session):
    df = session.createDataFrame([[1, 2, 3]]).toDF("col", '"col"', "col .")
    assert df.select(df["col"]).collect() == [Row(1)]
    assert df.select(df['"col"']).collect() == [Row(2)]
    assert df.select(df["col ."]).collect() == [Row(3)]
    assert df.select(df["COL"]).collect() == [Row(1)]
    assert df.select(df["CoL"]).collect() == [Row(1)]
    assert df.select(df['"COL"']).collect() == [Row(1)]

    with pytest.raises(SnowparkClientException) as ex_info:
        df.select(df['"Col"']).collect()
    assert "Cannot resolve column name" in str(ex_info)
    with pytest.raises(SnowparkClientException) as ex_info:
        df.select(df["COL ."]).collect()
    assert "Cannot resolve column name" in str(ex_info)
