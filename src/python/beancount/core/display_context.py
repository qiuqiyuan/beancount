"""A settings class to offer control over the number of digits rendered.

This module contains routines that can accumulate information on the width and
precision of numbers to be rendered and derive the precision required to render
all of them consistently and under certain common alignment requirements. This
is required in order to output neatly lined up columns of numbers in various
styles.

A common case is that the precision can be observed for numbers present in the
input file. This display precision can be used as the "precision by default" if
we write a routine for which it is inconvenient to feed all the numbers to build
such an accumulator.

Here are all the aspects supported by this module:

  PRECISION: Numbers for a particular currency are always rendered to the same
  precision, and they can be rendered to one of two precisions; either

    1. the most common number of fractional digits, or
    2. the maximum number of digits seen (this is useful for rendering prices).

  ALIGNMENT: Several alignment methods are supported.

    "natural": Render the strings as small as possible with no padding, but to
    their currency's precision. Like this:

      '1.2345'
      '764'
      '-7,409.01'
      '0.00000125'

    "dot-aligned": The periods will align vertically, the left and right sides
      are padded so that the column of numbers has the same width:

      '     1.2345    '
      '   764         '
      '-7,409.01      '
      '     0.00000125'

    "right": The strings are all flushed right, the left side is padded so that
      the column of numbers has the same width:

      '     1.2345'
      '        764'
      '  -7,409.01'
      ' 0.00000125'

  SIGN: If a negative sign is present in the input numbers, the rendered numbers
  reserve a space for it. If not, then we save the space.

  COMMAS: If the user requests to render commas, commas are rendered in the
  output.

  RESERVED: A number of extra integral digits reserved on the left in order to
  allow rendering novel numbers that haven't yet been seen.

"""
__author__ = "Martin Blais <blais@furius.ca>"

import collections
import io
import enum
import math
from pprint import pprint

from beancount.utils import misc_utils


class Precision(enum.Enum):
    """The type of precision required."""
    MOST_COMMON = 1
    MAXIMUM = 2


class Align(enum.Enum):
    """Alignment style for numbers."""
    NATURAL = 1
    DOT = 2
    RIGHT = 3


class _CurrencyContext:
    """A container of information for a single currency.

    This object accumulates aggregate information about numbers that is then
    used by the DisplayContext to manufacture appropriate Formatter
    objects.

    # Attributes:
    #   has_sign: A boolean, true if at least one of the numbers has a negative or
    #     explicit positive sign.
    #   integer_max: The maximum number of digits for the integer part.
    #   fractional_dist: A frequency distribution of fractionals seen in the input file.

    """
    def __init__(self):
        self.has_sign = False
        self.integer_max = 1
        self.fractional_dist = misc_utils.Distribution()

    def __str__(self):
        fmt = ('sign={:<2}  integer_max={:<2}  fractional_common={:<2}  fractional_max={:<2}  '
               '"{}" "{}"')
        dist = self.fractional_dist

        example = ''
        if self.has_sign:
            example += '-'
        example += '0' * self.integer_max

        example_common = example
        fractional_common = self.get_fractional(Precision.MOST_COMMON)
        if fractional_common is None:
            example_common = example + '.*'
        elif fractional_common > 0:
            example_common = example + '.' + ('0' * fractional_common)

        example_max = example
        fractional_max = self.get_fractional(Precision.MAXIMUM)
        if fractional_max is None:
            example_max = example + '.*'
        elif fractional_max > 0:
            example_max = example + '.' + ('0' * fractional_max)

        return fmt.format(
            int(self.has_sign),
            self.integer_max,
            '_' if dist.empty() else dist.mode(),
            '_' if dist.empty() else dist.max(),
            example_common, example_max)

    def update(self, number):
        # Note: Please do care for the performance of this routine. This is run
        # on a large set of numbers, possibly even during parsing. Consider
        # reimplementing this in C, after profiling.

        # Update the signs.
        num_tuple = number.as_tuple()
        if num_tuple.sign:
            self.has_sign = True

        # Update the precision.
        self.fractional_dist.update(-num_tuple.exponent)

        # Update the maximum number of integral digits.
        integer_digits = len(num_tuple.digits) + num_tuple.exponent
        self.integer_max = max(self.integer_max, integer_digits)

    def get_fractional(self, precision):
        """
        Returns:
          An integer for the number of fractional digits, or None.
        """
        if self.fractional_dist.empty():
            return None
        if precision == Precision.MOST_COMMON:
            return self.fractional_dist.mode()
        elif precision == Precision.MAXIMUM:
            return self.fractional_dist.max()
        else:
            raise ValueError("Unknown precision: {}".foramt(precision))


class DisplayContext:
    """A builder object used to construct a DisplayContext from a series of numbers.

    Attributes:
      builder_infos: A dict of currency string to BuilderCurrencyInfo instance.
    """
    def __init__(self):
        self.ccontexts = collections.defaultdict(_CurrencyContext)
        self.ccontexts['__default__'] = _CurrencyContext()

    def __str__(self):
        oss = io.StringIO()
        linefmt = '{:16}: {}\n'
        for currency, ccontext in sorted(self.ccontexts.items()):
            oss.write(linefmt.format(currency, ccontext))
        return oss.getvalue()

    def update(self, number, currency='__default__'):
        """Update the builder with the given number for the given currency.

        Args:
          number: An instance of Decimal to consider for this currency.
          currency: An optional string, the currency this numbers applies to.
        """
        self.ccontexts[currency].update(number)

    def build(self,
              alignment=Align.NATURAL,
              precision=Precision.MOST_COMMON,
              commas=None,
              reserved=0):
        if reserved != 0:
            raise NotImplementedError("Reserved digits aren't supported yet.")
        if alignment == Align.NATURAL:
            build_method = self._build_natural
        elif alignment == Align.RIGHT:
            build_method = self._build_right
        elif alignment == Align.DOT:
            build_method = self._build_dot
        else:
            raise ValueError("Unknown alignment: {}".foramt(alignment))
        fmtstrings = build_method(precision, commas, reserved)

        return DisplayFormatter(self, fmtstrings)

    def _build_natural(self, precision, commas, reserved):
        comma_str = ',' if commas else ''
        fmtstrings = {}
        for currency, ccontext in self.ccontexts.items():
            num_fractional_digits = ccontext.get_fractional(precision)
            fmtfmt = ('{{:{comma}}}'
                      if num_fractional_digits is None
                      else '{{:{comma}.{frac}f}}')
            fmtstrings[currency] = fmtfmt.format(comma=comma_str,
                                                 frac=num_fractional_digits)
        return fmtstrings

    def _build_right(self, precision, commas, reserved):
        # Compute an upper bound for the required width.
        max_digits_list = []
        for ccontext in self.ccontexts.values():
            max_digits = 0
            if ccontext.has_sign:
                max_digits += 1
            max_digits += ccontext.integer_max
            if commas:
                max_digits += int(ccontext.integer_max / 3)
            num_fractional_digits = ccontext.get_fractional(precision)
            if num_fractional_digits is not None:
                if num_fractional_digits != 0:
                    max_digits += 1  # period
                max_digits += num_fractional_digits
            max_digits_list.append(max_digits)
        max_width = max(max_digits_list)

        # Compute the format strings.
        comma_str = ',' if commas else ''
        fmtstrings = {}
        for currency, ccontext in self.ccontexts.items():
            num_fractional_digits = ccontext.get_fractional(precision)
            fmtfmt = ('{{:{width}{comma}}}'
                      if num_fractional_digits is None
                      else '{{:{width}{comma}.{frac}f}}')
            fmtstrings[currency] = fmtfmt.format(comma=comma_str,
                                                 width=max_width,
                                                 frac=num_fractional_digits)
        return fmtstrings

    DEFAULT_UNINITIALIZED_PRECISION = 8

    def _build_dot(self, precision, commas, reserved):
        # Compute an upper bound for the required width.
        max_sign = 0
        max_integer = 0
        max_period = 0
        max_fractional = -1
        for ccontext in self.ccontexts.values():
            if ccontext.has_sign:
                max_sign = 1

            num_integer = ccontext.integer_max
            if commas:
                num_integer += int(num_integer / 3)
            max_integer = max(max_integer, num_integer)

            num_fractional_digits = ccontext.get_fractional(precision)
            if num_fractional_digits is not None:
                if num_fractional_digits > 0:
                    max_period = 1
                max_fractional = max(max_fractional, num_fractional_digits)

        if max_fractional == -1:
            max_fractional = self.DEFAULT_UNINITIALIZED_PRECISION

        max_width = sum([max_sign, max_integer, max_period, max_fractional])

        # Compute the format strings.
        comma_str = ',' if commas else ''
        sign_str = ' ' if max_sign else ''
        fmtstrings = {}
        for currency, ccontext in self.ccontexts.items():
            num_fractional_digits = ccontext.get_fractional(precision)
            if num_fractional_digits is None:
                num_fractional_digits = max_fractional
            len_padding = max_fractional - num_fractional_digits
            if max_fractional > 0 and num_fractional_digits == 0:
                len_padding += 1
            fmtfmt = '{{:{sign}{width}{comma}.{frac}f}}' + (' ' * len_padding)
            fmtstrings[currency] = fmtfmt.format(sign=sign_str,
                                                 comma=comma_str,
                                                 width=max_width - len_padding,
                                                 frac=num_fractional_digits)
        return fmtstrings


class DisplayFormatter:
    """A class used to contain various settings that control how we output numbers.
    In particular, the precision used for each currency, and whether or not
    commas should be printed. This object is intended to be passed around to all
    functions that format numbers to strings.

    Attributes:

      # commas: A boolean, whether we should render commas or not.
      # signs: A boolean, whether to always render the signs.
      # fractional: A dict of currency to fractional. A key of None provides the
      #   default precision. A special value of FULL_PRECISION indicates we should render
      #   at the natural precision for the given number.
      # fractional_max: Like 'fractional' but for maximum number of digits.
      # formats: A dict of currency to a pre-baked format string to render a
      #   number. (A key of None is treated as for self.fractional.)
      # formats_max: Like 'formats' but for maximum number of digits.
      # default_format: The default display format.
    """
    def __init__(self, dcontext, fmtstrings):
        self.dcontext = dcontext
        self.fmtstrings = fmtstrings
        self.fmtfuncs = {currency: fmtstr.format
                         for currency, fmtstr in fmtstrings.items()}

    def __str__(self):
        return 'DisplayFormatter({})'.format(self.fmtstrings)

    def format(self, number, currency='__default__'):
        try:
            func = self.fmtfuncs[currency]
        except KeyError:
            func = self.fmtfuncs['__default__']
        return func(number)

    __call__ = format


# Default instance of DisplayContext to use if None is spcified.
DEFAULT_DISPLAY_CONTEXT = DisplayContext()
DEFAULT_FORMATTER = DEFAULT_DISPLAY_CONTEXT.build()