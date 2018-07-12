import decimal
import io
from nose.tools import assert_equal
import utcdatetime

from os.path import join as pjoin

from snipe import WatchListSnipesParser, parse_datetime


def test_get_snipes():
    with io.open(pjoin('sample_data', 'watch_list.html')) as f:
        parser = WatchListSnipesParser(f.read())

    assert_equal(
        list(parser.get_snipes()), [
            ('113143572176', decimal.Decimal('7.00')),
            ('292631197506', decimal.Decimal('44.00')),
        ]
    )


def test_parse_snipe_note():
    TEST_CASES = [
        ('snipe: 45', decimal.Decimal(45.00)),
        ('snipe: 45.00', decimal.Decimal(45.00)),
        ('snipe: £45.00', decimal.Decimal(45.00)),
    ]

    for note, expected_amount in TEST_CASES:
        yield assert_equal, WatchListSnipesParser._parse_snipe_note(note), expected_amount


def test_parse_datetime():
    TEST_CASES = [
        (
            '(11 Jul, 2018\n09:58:34 BST)',
            utcdatetime.utcdatetime(2018, 7, 11, 8, 58, 34)
        ),
        (
            '(11 Jan, 2018\n09:58:34 GMT)',
            utcdatetime.utcdatetime(2018, 1, 11, 9, 58, 34)
        ),
    ]

    for string, expected in TEST_CASES:
        yield assert_equal, parse_datetime(string), expected
