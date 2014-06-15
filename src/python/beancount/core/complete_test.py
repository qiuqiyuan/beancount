import unittest
import copy

from beancount.core.data import create_simple_posting, create_simple_posting_with_cost
from beancount.core import complete
from beancount.core import data
from beancount.core import complete
from beancount.core import amount
from beancount.parser import parser


class TestBalance(unittest.TestCase):

    def test_get_balance_amount(self):

        # Entry without cost, without price.
        posting = create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD")
        self.assertEqual(amount.Amount("105.50", "USD"),
                         complete.get_balance_amount(posting))

        # Entry without cost, with price.
        posting = posting._replace(price=amount.Amount("0.90", "CAD"))
        self.assertEqual(amount.Amount("94.95", "CAD"),
                         complete.get_balance_amount(posting))

        # Entry with cost, without price.
        posting = create_simple_posting_with_cost(None, "Assets:Bank:Checking",
                                                  "105.50", "USD", "0.80", "EUR")
        self.assertEqual(amount.Amount("84.40", "EUR"),
                         complete.get_balance_amount(posting))

        # Entry with cost, and with price (the price should be ignored).
        posting = posting._replace(price=amount.Amount("2.00", "CAD"))
        self.assertEqual(amount.Amount("84.40", "EUR"),
                         complete.get_balance_amount(posting))

    def test_has_nontrivial_balance(self):

        # Entry without cost, without price.
        posting = create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD")
        self.assertFalse(complete.has_nontrivial_balance(posting))

        # Entry without cost, with price.
        posting = posting._replace(price=amount.Amount("0.90", "CAD"))
        self.assertTrue(complete.has_nontrivial_balance(posting))

        # Entry with cost, without price.
        posting = create_simple_posting_with_cost(None, "Assets:Bank:Checking",
                                                  "105.50", "USD", "0.80", "EUR")
        self.assertTrue(complete.has_nontrivial_balance(posting))

        # Entry with cost, and with price (the price should be ignored).
        posting = posting._replace(price=amount.Amount("2.00", "CAD"))
        self.assertTrue(complete.has_nontrivial_balance(posting))

    def test_compute_residual(self):

        # Try with two accounts.
        residual = complete.compute_residual([
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Checking", "-194.50", "USD"),
            ])
        self.assertEqual([amount.Amount("-89", "USD")], residual.get_amounts())

        # Try with more accounts.
        residual = complete.compute_residual([
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Checking", "-194.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Investing", "5", "AAPL"),
            create_simple_posting(None, "Assets:Bank:Savings", "89.00", "USD"),
            ])
        self.assertEqual([amount.Amount("5", "AAPL")], residual.get_amounts())

    def test_get_incomplete_postings_pathological(self):
        fileloc = data.FileLocation(__file__, 0)

        # Test with no entries.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(0, len(new_postings))
        self.assertEqual(0, len(errors))

        # Test with only a single leg (and check that it does not balance).
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(1, len(new_postings))
        self.assertEqual(1, len(errors))

        # Test with two legs that balance.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Savings", "-105.50", "USD"),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(2, len(new_postings))
        self.assertEqual(0, len(errors))

        # Test with two legs that do not balance.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Savings", "-115.50", "USD"),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(2, len(new_postings))
        self.assertEqual(1, len(errors))

        # Test with only one auto-posting.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", None, None),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(0, len(new_postings))
        self.assertEqual(1, len(errors))

        # Test with an auto-posting where there is no residual.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Savings", "-105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Balancing", None, None),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertTrue(has_inserted)
        self.assertEqual(3, len(new_postings))
        self.assertEqual(1, len(errors))

        # Test with too many empty postings.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Savings", "-106.50", "USD"),
            create_simple_posting(None, "Assets:Bank:BalancingA", None, None),
            create_simple_posting(None, "Assets:Bank:BalancingB", None, None),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertTrue(has_inserted)
        self.assertEqual(3, len(new_postings))
        self.assertEqual(1, len(errors))

    def test_get_incomplete_postings_normal(self):
        fileloc = data.FileLocation(__file__, 0)

        # Test with a single auto-posting with a residual.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Assets:Bank:Checking", "105.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Savings", "-115.50", "USD"),
            create_simple_posting(None, "Assets:Bank:Balancing", None, None),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertTrue(has_inserted)
        self.assertEqual(3, len(new_postings))
        self.assertEqual(0, len(errors))

    def test_balance_with_large_amount(self):
        fileloc = data.FileLocation(__file__, 0)

        # Test with a single auto-posting with a residual.
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Income:US:Anthem:InsurancePayments",
                                  "-275.81", "USD"),
            create_simple_posting(None, "Income:US:Anthem:InsurancePayments",
                                  "-23738.54", "USD"),
            create_simple_posting(None, "Assets:Bank:Checking",
                                  "24014.45", "USD"),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(3, len(new_postings))
        self.assertEqual(1, len(errors))

    def test_balance_with_zero_posting(self):
        fileloc = data.FileLocation(__file__, 0)
        entry = data.Transaction(fileloc, None, None, None, None, None, None, [
            create_simple_posting(None, "Income:US:Anthem:InsurancePayments", "0", "USD"),
            create_simple_posting(None, "Income:US:Anthem:InsurancePayments", None, None),
            ])
        new_postings, has_inserted, errors = complete.get_incomplete_postings(entry)
        self.assertFalse(has_inserted)
        self.assertEqual(1, len(new_postings))
        self.assertEqual(0, len(errors))

    def balance_incomplete_postings(self):
        entry = parser.parse_string("""
          2013-02-23 * "Something"
            Liabilities:CreditCard     -50 USD
            Expenses:Restaurant         50 USD
        """)[0][0]
        orig_entry = copy.deepcopy(entry)
        errors = complete.balance_incomplete_postings(entry)
        self.assertFalse(errors)
        self.assertEqual(orig_entry, entry)

        entry = parser.parse_string("""
          2013-02-23 * "Something"
            Liabilities:CreditCard     -50 USD
            Expenses:Restaurant
        """)[0][0]
        orig_entry = copy.deepcopy(entry)
        errors = complete.balance_incomplete_postings(entry)
        self.assertFalse(errors)
        self.assertEqual(strip_recursive(orig_entry),
                         strip_recursive(entry))

        entry = parser.parse_string("""
          2013-02-23 * "Something"
            Liabilities:CreditCard     -50 USD
            Liabilities:CreditCard     -50 CAD
            Expenses:Restaurant
        """)[0][0]
        errors = complete.balance_incomplete_postings(entry)
        self.assertFalse(errors)
        self.assertEqual(4, len(entry.postings))