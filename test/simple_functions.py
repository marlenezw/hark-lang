import time
import random
from random import randint


def plus1(x):
    return x + 1


def times2(x):
    time.sleep(randint(1, 3))
    return x * 2


def times3(x):
    time.sleep(randint(1, 3))
    return x * 3


def sum_two(a, b):
    return a + b


def printit(arg):
    print(arg)


class Buf:
    def __init__(self):
        self.output = ""

    def puts(self, val):
        self.output += f"{val}\n"
