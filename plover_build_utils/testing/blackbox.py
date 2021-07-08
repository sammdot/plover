import ast
import functools
import inspect
import operator
import re
import textwrap

from plover.formatting import Formatter
from plover.steno import normalize_steno
from plover.steno_dictionary import StenoDictionary
from plover.translation import Translator

from .output import CaptureOutput
from .steno import steno_to_stroke


BLACKBOX_OUTPUT_RX = re.compile("r?['\"]")


def blackbox_setup(blackbox):
    blackbox.output = CaptureOutput()
    blackbox.formatter = Formatter()
    blackbox.formatter.set_output(blackbox.output)
    blackbox.translator = Translator()
    blackbox.translator.set_min_undo_length(100)
    blackbox.translator.add_listener(blackbox.formatter.format)
    blackbox.dictionary = blackbox.translator.get_dictionary()
    blackbox.dictionary.set_dicts([StenoDictionary()])


def blackbox_replay(blackbox, name, test):
    # Hide from traceback on assertions (reduce output size for failed tests).
    __tracebackhide__ = operator.methodcaller('errisinstance', AssertionError)
    definitions, instructions = test.strip().rsplit('\n\n', 1)
    for steno, translation in ast.literal_eval(
        '{' + definitions + '}'
    ).items():
        blackbox.dictionary.set(normalize_steno(steno), translation)
    # Track line number for a more user-friendly assertion message.
    lines = test.split('\n')
    lnum = len(lines)-3 - test.rstrip().rsplit('\n\n', 1)[1].count('\n')
    for step in re.split('(?<=[^\\\\])\n', instructions):
        # Mark current instruction's line.
        lnum += 1
        step = step.strip()
        # Support for changing some settings on the fly.
        if step.startswith(':'):
            action = step[1:]
            if action == 'start_attached':
                blackbox.formatter.start_attached = True
            elif action == 'spaces_after':
                blackbox.formatter.set_space_placement('After Output')
            elif action == 'spaces_before':
                blackbox.formatter.set_space_placement('Before Output')
            else:
                raise ValueError('invalid action:\n%s' % msg)
            continue
        steno, output = step.split(None, 1)
        steno = list(map(steno_to_stroke, normalize_steno(steno.strip())))
        output = output.strip()
        assert_msg = (
            name + '\n' +
            '\n'.join(('> ' if n == lnum else '  ') + l
                      for n, l in enumerate(lines)) + '\n'
        )
        if BLACKBOX_OUTPUT_RX.match(output):
            # Replay strokes.
            list(map(blackbox.translator.translate, steno))
            # Check output.
            expected_output = ast.literal_eval(output)
            assert_msg += (
                '   ' + repr(blackbox.output.text) + '\n'
                '!= ' + repr(expected_output)
            )
            assert blackbox.output.text == expected_output, assert_msg
        elif output.startswith('raise '):
            expected_exception = output[6:].strip()
            try:
                list(map(blackbox.translator.translate, steno))
            except Exception as e:
                exception_class = e.__class__.__name__
            else:
                exception_class = 'None'
            assert_msg += (
                '   ' + exception_class + '\n'
                '!= ' + expected_exception
            )
            assert exception_class == expected_exception, assert_msg
        else:
            raise ValueError('invalid output:\n%s' % output)


def blackbox_test(cls_or_fn):

    if inspect.isclass(cls_or_fn):

        class wrapper(cls_or_fn):
            pass

        for name in dir(wrapper):
            if name.startswith('test_'):
                fn = getattr(wrapper, name)
                new_fn = blackbox_test(fn)
                setattr(wrapper, name, new_fn)

    else:

        name = cls_or_fn.__name__
        test = textwrap.dedent(cls_or_fn.__doc__)
        # Use a lamdbda to reduce output size for failed tests.
        wrapper = lambda bb, *args, **kwargs: (blackbox_setup(bb), cls_or_fn(bb, *args, **kwargs), blackbox_replay(bb, name, test))
        wrapper = functools.wraps(cls_or_fn)(wrapper)

    return wrapper
