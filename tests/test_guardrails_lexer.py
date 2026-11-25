"""The guardrails shell lexer on its own: what counts as a command, a word and a substitution."""

from __future__ import annotations

from typing import Any

from test_guardrails_support import G


def commands(text: str) -> list[Any]:
    return [item for item in G.parse(text) if isinstance(item, G.Command)]


def cmds(text: str) -> list[list[str]]:
    return [[w.text for w in item.words] for item in commands(text)]


def test_separators_split_commands() -> None:
    assert cmds("a; b && c || d & e\nf") == [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]


def test_pipe_keeps_stages_in_one_pipeline() -> None:
    items = commands("a | b | c; d")
    first = items[0].pipeline
    assert [(i.pipeline, i.pos) for i in items[:3]] == [(first, 0), (first, 1), (first, 2)]
    assert items[3].pos == 0 and items[3].pipeline != first


def test_quotes_and_escapes() -> None:
    assert cmds("echo 'a b' \"c d\" e\\ f") == [["echo", "a b", "c d", "e f"]]
    assert cmds('echo "a \\" b"') == [["echo", 'a " b']]
    assert cmds("echo ''") == [["echo", ""]]
    assert cmds('echo "" x') == [["echo", "", "x"]]
    assert cmds("g'i't") == [["git"]]


def test_operators_inside_quotes_are_text() -> None:
    assert cmds("echo 'a; b && c | d'") == [["echo", "a; b && c | d"]]
    assert cmds('echo "a ; b"') == [["echo", "a ; b"]]


def test_ansi_c_quoting_is_decoded() -> None:
    assert cmds("echo $'\\x2d\\x66' $'a\\tb'") == [["echo", "-f", "a\tb"]]


def test_line_continuation_joins_lines() -> None:
    assert cmds("git push \\\n  origin main") == [["git", "push", "origin", "main"]]


def test_comments_are_dropped_but_hash_inside_a_word_is_kept() -> None:
    assert cmds("echo a # git push origin main\necho b#c") == [["echo", "a"], ["echo", "b#c"]]


def test_assignments_before_the_command_are_split_off() -> None:
    item = commands("A=1 B='x y' cmd C=3")[0]
    assert [(n, w.text) for n, w in item.assigns] == [("A", "1"), ("B", "x y")]
    assert [w.text for w in item.words] == ["cmd", "C=3"]


def test_keywords_are_skipped_at_command_position() -> None:
    assert cmds("if true; then git push; fi") == [["true"], ["git", "push"]]
    assert cmds("while read l; do echo $l; done") == [["read", "l"], ["echo", "$l"]]


def test_redirects_are_not_arguments() -> None:
    item = commands("cmd a >out 2>&1 <in")[0]
    assert [w.text for w in item.words] == ["cmd", "a"]
    assert [(op, w.text) for op, w in item.redirects] == [(">", "out"), (">&", "1"), ("<", "in")]


def test_command_and_process_substitutions_are_collected() -> None:
    words = commands('x "$(a b)" `c d` <(e f) $(g $(h))')[0].words
    assert [w.subs for w in words[1:]] == [["a b"], ["c d"], ["e f"], ["g $(h)"]]
    assert words[3].procsub and not words[1].procsub


def test_arithmetic_is_not_a_command() -> None:
    items = G.parse("echo $((1 + 2)) done")
    assert len(items) == 1  # no stray ")" marker is left behind
    assert [w.text for w in items[0].words] == ["echo", "$((1 + 2))", "done"]
    assert items[0].words[1].subs == []


def test_heredoc_body_is_data_and_attached_to_its_command() -> None:
    items = commands("cat <<'EOF' > f\ngit push origin main\nEOF\necho after")
    assert [[w.text for w in i.words] for i in items] == [["cat"], ["echo", "after"]]
    assert items[0].heredocs == ["git push origin main\n"]


def test_heredoc_with_tab_stripping_and_two_heredocs() -> None:
    items = commands("cat <<-A <<B\n\tone\n\tA\ntwo\nB\nnext")
    assert [[w.text for w in i.words] for i in items] == [["cat"], ["next"]]
    assert len(items[0].heredocs) == 2


def test_apostrophes_inside_a_heredoc_in_a_substitution_do_not_swallow_the_rest() -> None:
    text = "git commit -m \"$(cat <<'EOF'\ndon't (stop)\nEOF\n)\" && git push origin main"
    assert cmds(text)[-1] == ["git", "push", "origin", "main"]


def test_unterminated_constructs_end_at_the_end_of_the_text() -> None:
    assert cmds("echo 'abc") == [["echo", "abc"]]
    assert cmds('echo "abc') == [["echo", "abc"]]
    assert cmds("echo $(abc") == [["echo", "$(abc"]]
    assert cmds("echo `abc") == [["echo", "`abc`"]]
    assert cmds("") == []
    assert cmds("   \n\n  ") == []


def test_subshell_markers() -> None:
    kinds = [i if isinstance(i, str) else "cmd" for i in G.parse("(a; b); c")]
    assert kinds == ["(", "cmd", "cmd", ")", "cmd"]


def test_wrappers_are_stripped() -> None:
    def argv(text: str) -> tuple[list[str], list[str]]:
        env, words = G.unwrap(commands(text)[0].words)
        return env, [w.text for w in words]

    assert argv("sudo -u root -E git push") == ([], ["git", "push"])
    assert argv("env FOO=1 -i BAR=2 git push") == (["FOO=1", "BAR=2"], ["git", "push"])
    assert argv("timeout 5 git push") == ([], ["git", "push"])
    assert argv("nohup nice -n 10 git push") == ([], ["git", "push"])
    assert argv("xargs -I{} git push") == ([], ["git", "push"])
    assert argv("git push") == ([], ["git", "push"])
