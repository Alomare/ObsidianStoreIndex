# Self-test of tools/validate.py, offline:  python tools/test_validate.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate import diff_problems, readme_words, text_problem  # noqa: E402


def eq(got, want, what):
    assert got == want, f"{what}: got {got!r}, want {want!r}"


def test_text():
    eq(text_problem("Better HUD", "name"), None, "name")
    eq(text_problem("Photo Mode", "name"), None, "name")
    eq(text_problem("Shows ammo, grenades and stratagem cooldowns in a cleaner layout.", "summary"), None, "summary")
    eq(text_problem("Mostra munição e granadas num layout mais limpo para o jogador.", "summary"), None, "Portuguese")
    eq(text_problem("在游戏中显示弹药和手雷，界面更清晰，适合所有玩家使用的模组", "summary"), None, "Chinese")
    eq(text_problem("Great mod, install it", "summary"), None, "four words")
    eq(text_problem("This mod replaces the heads-up display of the game with a cleaner one. " * 4, "readme"), None, "readme")
    eq(text_problem("ab", "name"), "short", "short")
    for junk in ("asdf", "Test", "My Mod"):
        eq(text_problem(junk, "name"), "placeholder", junk)
    eq(text_problem("Lorem ipsum dolor sit amet consectetur", "summary"), "placeholder", "lorem")
    eq(text_problem("sdfkjh qwrtpl zxcvbn mnbvcx lkjhg", "summary"), "placeholder", "keyboard row")
    eq(text_problem("sdfkjh wrtpl bvcxzm nbvcx lkjhgf", "summary"), "gibberish", "no vowels")
    eq(text_problem("this mod is goooooood for you all", "summary"), "repeated", "repeated")
    eq(text_problem("!!! ### $$$ %%% ^^^ &&& ***", "summary"), "symbols", "symbols")
    eq(text_problem("THIS MOD IS THE BEST MOD EVER MADE", "summary"), "shouting", "shouting")
    eq(text_problem("Wonderful, essential modification", "summary"), "words", "words")
    eq(text_problem("A mod abcdefghijklmnopqrstuvwxyzabcdefghij that does things", "summary"), "gibberish", "long word")
    eq(text_problem("Short readme.", "readme"), "short", "short readme")


def test_readme_words():
    md = "# Title\n\n![shot](img/a.png)\n\nSee [the wiki](https://x.y/z) for <b>more</b>.\n\n```lua\nlocal x = 1\n```\n"
    w = readme_words(md)
    assert "Title" in w and "See the wiki for more." in w, w
    assert "https" not in w and "local x" not in w and "img/a.png" not in w, w


def test_diff():
    base = {"verified": ["Alomare"], "kit": ["Alomare/ObsidianAPI"], "mods": ["Alomare/A", "Alomare/B"]}
    head = dict(base, mods=base["mods"] + ["someone/C"])
    eq(diff_problems(base, head), ([], ["someone/C"]), "append")
    problems, added = diff_problems(base, dict(base, mods=["Alomare/B", "Alomare/A", "someone/C"]))
    assert problems and not added, "reorder"
    problems, added = diff_problems(base, dict(base, mods=["Alomare/A", "someone/C"]))
    assert problems and not added, "remove"
    problems, _ = diff_problems(base, dict(base, kit=base["kit"] + ["someone/C"]))
    assert any("kit" in p for p in problems), "kit change"
    problems, _ = diff_problems(base, dict(head, verified=["Alomare", "someone"]))
    assert any("verified" in p for p in problems), "verified change"
    problems, _ = diff_problems(base, dict(head, private=[]))
    assert any("private" in p for p in problems), "private added"
    problems, _ = diff_problems(base, base)
    assert problems, "nothing added"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
