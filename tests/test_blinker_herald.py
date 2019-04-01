#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable-all
"""
test_blinker_herald
----------------------------------

Tests for `blinker_herald` module.
"""
from unittest import TestCase  # pylint:disable=import-error
from nailgun.blinker_herald import (
    emit, signals, AbstractSender, Namespace,
    SENDER_CLASS, SENDER_CLASS_NAME, SENDER_MODULE
)


class TestBlinkerHerald(TestCase):

    def test_emit_decorator_in_function(self):
        """Should assert that emit decorator is working"""

        abstract_sender = AbstractSender()

        @emit(sender=abstract_sender)
        def simple_function1(arg1, arg2=None):
            return '{} it worked {}'.format(arg1, arg2)

        @simple_function1.pre.connect
        def handle_pre(sender, **kwargs):
            sender.pre_emitted = True

        @simple_function1.post.connect
        def handle_post(sender, **kwargs):
            sender.post_emitted = True

        assert getattr(abstract_sender, 'pre_emitted', None) is None
        assert getattr(abstract_sender, 'post_emitted', None) is None

        simple_function1('\n# hello', arg2='world')

        assert abstract_sender.pre_emitted is True
        assert abstract_sender.post_emitted is True

    def test_emit_decorator_in_function_with_args(self):
        """Should assert that decorated funtion arguments
        positional and named is being passed to handlers"""

        abstract_sender = AbstractSender()

        @emit(sender=abstract_sender)
        def simple_function2(arg1, arg2, arg3=None):
            return '{} it worked {}'.format(arg1, arg2)

        @simple_function2.pre.connect
        def handle_pre(sender, **kwargs):
            sender.pre_emitted = True
            assert kwargs['arg1'] == 'hello'
            assert kwargs['arg2'] == 'world'
            assert kwargs['arg3'] == 'dude'

        @simple_function2.post.connect
        def handle_post(sender, **kwargs):
            sender.post_emitted = True
            assert kwargs['arg1'] == 'hello'
            assert kwargs['arg2'] == 'world'
            assert kwargs['arg3'] == 'dude'

        assert getattr(abstract_sender, 'pre_emitted', None) is None
        assert getattr(abstract_sender, 'post_emitted', None) is None

        simple_function2('hello', arg2='world', arg3='dude')

        assert abstract_sender.pre_emitted is True
        assert abstract_sender.post_emitted is True

    def test_emit_decorator_in_function_w_limited_args(self, *args, **kwargs):
        """Assert that only limited arguments are passed in each signal"""
        abstract_sender = AbstractSender()

        @emit(sender=abstract_sender,
              return_vars={'pre': ['arg1', 'arg2'],
                           'post': ['arg2', 'arg3']})
        def simple_function3(arg1, arg2, arg3=None):
            return '{} it worked {}'.format(arg1, arg2)

        @simple_function3.pre.connect
        def handle_pre(sender, **kwargs):
            sender.pre_emitted = True
            assert kwargs['arg1'] == 'hello'
            assert kwargs['arg2'] == 'world'
            assert 'arg3' not in kwargs

        @simple_function3.post.connect
        def handle_post(sender, **kwargs):
            sender.post_emitted = True
            assert 'arg1' not in kwargs
            assert kwargs['arg2'] == 'world'
            assert kwargs['arg3'] == 'dude'

        assert getattr(abstract_sender, 'pre_emitted', None) is None
        assert getattr(abstract_sender, 'post_emitted', None) is None

        simple_function3('hello', 'world', arg3='dude')

        assert abstract_sender.pre_emitted is True
        assert abstract_sender.post_emitted is True

    def test_emit_deco_in_function_w_defined_returnname(self, *args, **kwargs):
        """Assert the ability to define result name for post-signals
        also takes care of the only argument"""

        abstract_sender = AbstractSender()

        @emit(
            sender=abstract_sender,
            only='post',
            post_result_name='foo'
        )
        def simple_function4(arg1, arg2, arg3=None):
            return '{} it worked {}'.format(arg1, arg2)

        @simple_function4.pre.connect
        def handle_pre(sender, **kwargs):
            """This should not be handle because we limited to post only"""
            raise RuntimeError("This handler should never run")

        @simple_function4.post.connect
        def handle_post(sender, **kwargs):
            sender.post_emitted = True
            assert 'foo' in kwargs

        @simple_function4.post.connect
        def handle_post2(sender, foo, **kwargs):
            sender.post_emitted = True
            assert foo == 'hello it worked world'
            sender.foo = foo

        assert getattr(abstract_sender, 'pre_emitted', None) is None
        assert getattr(abstract_sender, 'post_emitted', None) is None

        simple_function4('hello', arg2='world', arg3='dude')

        assert abstract_sender.post_emitted is True
        assert abstract_sender.foo == 'hello it worked world'

    def test_emit_decorator_in_method(self, *args, **kwargs):
        class Dummy(object):
            @emit(post_result_name='foo')
            def simple_method(self, arg1, arg2, arg3=None):
                return 'bar'

        @Dummy.simple_method.pre.connect
        def handle_method_pre(sender, arg1, **kwargs):
            sender.pre_emitted = True
            assert arg1 == 'hello'
            assert kwargs['arg2'] == 'world'
            assert kwargs['arg3'] is None

        @Dummy.simple_method.post.connect
        def handle_method_post(sender, arg1, **kwargs):
            sender.post_emitted = True
            assert arg1 == 'hello'
            assert kwargs['arg2'] == 'world'
            assert kwargs['arg3'] is None
            assert kwargs['foo'] == 'bar'

        d = Dummy()
        d.simple_method('hello', 'world')
        assert d.pre_emitted is True
        assert d.post_emitted is True

    def test_emit_decorator_in_method_w_limited_args(self, *args, **kwargs):
        class Dummy2(object):
            @emit(post_result_name='foo', return_vars=['arg2'])
            def simple_method(self, arg1, arg2, arg3=None):
                return 'bar'

        @Dummy2.simple_method.pre.connect
        def handle_method_pre(sender, arg2, **kwargs):
            assert isinstance(sender, Dummy2)
            sender.pre_emitted = True
            assert arg2 == 'world'

        @Dummy2.simple_method.post.connect
        def handle_method_post(sender, foo, arg2, **kwargs):
            sender.post_emitted = True
            assert arg2 == 'world'
            assert foo == 'bar'

        d = Dummy2()
        d.simple_method('hello', 'world')
        assert d.pre_emitted is True
        assert d.post_emitted is True

    def test_custom_namespace(self, *args, **kwargs):
        customnamespace = Namespace()
        pre_signal = customnamespace.signal('pre_test_function')
        post_signal = customnamespace.signal('post_test_function')

        @emit(sender='test', namespace=customnamespace)
        def test_function(arg1, arg2='default'):
            return 'result'

        @test_function.pre.connect
        def handle_pre(sender, arg1, **kw):
            assert arg1 == 'foo'
            assert kw['arg2'] == 'default'

        @pre_signal.connect
        def another_pre_handler(sender, **kw):
            assert kw['arg1'] == 'foo'

        @post_signal.connect
        def handle_post(sender, **kwargs):
            assert sender == 'test'
            assert kwargs['result'] == 'result'

        test_function('foo')

    def test_custom_no_result_no_args(self, *args, **kwargs):
        @emit(sender='test', capture_result=False)
        def test_function():
            return 'result'

        @test_function.pre.connect
        def handle_pre(sender, signal_emitter):
            """should fail if get extra args"""
            assert sender == 'test'

        @test_function.post.connect
        def handle_post(sender, signal_emitter):
            """should fail if get extra args"""
            assert sender == 'test'

        test_function()

    def test_function_sender_is_required(self, *args, **kwargs):
        with self.assertRaises(RuntimeError):
            @emit()  # no sender specified
            def test_no_sender():
                return

    def test_connected_to_specific_sender_str_in_method(self, *args, **kwargs):
        class AClass(object):
            @emit(post_result_name='foo', sender='base')
            def a_simple_method(self):
                return 'bar'

        @AClass.a_simple_method.pre.connect
        def handle_aclass_method(sender, **kwargs):
            assert sender == 'base'
            # signal_emitter is always 'self', 'cls' or function reference
            kwargs['signal_emitter'].emitted = True

        a = AClass()
        a.a_simple_method()
        assert a.emitted is True

    def test_connected_using_sender_class_name(self, *args, **kwargs):
        class BClass(object):
            @emit(post_result_name='foo',
                  sender=SENDER_CLASS_NAME)
            def b_simple_method(self):
                return 'bar'

        @BClass.b_simple_method.pre.connect
        def handle_bclass_method(sender, **kwargs):
            assert sender == BClass.__name__

        b = BClass()
        b.b_simple_method()

    def test_connected_to_using_class(self, *args, **kwargs):
        class CClass(object):
            @emit(post_result_name='foo',
                  sender=SENDER_CLASS)
            def c_simple_method(self):
                return 'bar'

        @CClass.c_simple_method.pre.connect
        def base_handle_pre(sender, **kwargs):
            assert issubclass(sender, CClass)

        class One(CClass):
            pass

        o = One()
        o.c_simple_method()

    def test_connected_to_using_module(self, *args, **kwargs):
        class DClass(object):
            @emit(post_result_name='foo',
                  sender=SENDER_MODULE)
            def d_simple_method(self):
                return 'bar'

        @DClass.d_simple_method.pre.connect
        def base_handle_pre(sender, **kwargs):
            assert sender == DClass.__module__

        class One(DClass):
            pass

        o = One()
        o.d_simple_method()

    def test_connected_via_to_specific_handler(self, *args, **kwargs):
        class Base(object):
            @emit(post_result_name='foo',
                  sender=SENDER_CLASS)
            def base_simple_method(self):
                return 'bar'

        class One(Base):
            pass

        class Two(Base):
            pass

        @Base.base_simple_method.pre.connect_via(One)
        def base_handle_pre_for_one(sender, **kwargs):
            assert issubclass(sender, Base)
            assert sender == One
            assert kwargs['signal_emitter'].__class__.__name__ == 'One'

        def base_handle_pre_for_two(sender, **kwargs):
            assert issubclass(sender, Base)
            assert sender == Two
            assert kwargs['signal_emitter'].__class__.__name__ == 'Two'

        Base.base_simple_method.pre.connect(
            base_handle_pre_for_two, sender=Two
        )

        o = One()
        o.base_simple_method()

        t = Two()
        t.base_simple_method()

    def test_emit_using_lambda_sender(self):

        class Test(object):
            @emit(sender=lambda s: "sender_{0}".format(s.__class__.__name__))
            def test_method(self, arg1):
                return arg1

        @signals.post_test_method.connect
        def test_method_handler(sender, signal_emitter, result, **kwargs):
            assert sender == 'sender_Test'
            assert result == 'foo'
            assert isinstance(signal_emitter, Test)
            signal_emitter.post_emitted = True

        t = Test()
        t.test_method('foo')
        assert t.post_emitted is True
