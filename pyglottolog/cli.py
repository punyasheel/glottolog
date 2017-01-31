# coding: utf8
"""
Main command line interface of the pyglottolog package.

Like programs such as git, this cli splits its functionality into sub-commands
(see e.g. https://docs.python.org/2/library/argparse.html#sub-commands).
The rationale behind this is that while a lot of different tasks may be triggered using
this cli, most of them require common configuration.

The basic invocation looks like

    glottolog [OPTIONS] <command> [args]

"""
from __future__ import unicode_literals, print_function
import sys
from collections import Counter, defaultdict
import logging

from clldutils.clilib import ArgumentParser, ParserError
from clldutils.path import copytree, rmtree, remove, Path
from clldutils.iso_639_3 import ISO
from clldutils.markup import Table

from pyglottolog.monster import main as compile_monster
from pyglottolog.languoids import (
    make_index, Languoid, find_languoid, Glottocode, Glottocodes, walk_tree, Level,
    ascii_tree,
)
from pyglottolog.util import DATA_DIR, languoids_path, build_path
from pyglottolog import lff
from pyglottolog import fts
from pyglottolog.api import Glottolog


logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)


def monster(args):
    """Compile the monster bibfile from the BibTeX files listed in references/BIBFILES.ini

    glottolog monster
    """
    compile_monster(repos=args.repos)


def index(args):
    """Create an index page listing and linking to all languoids of a specified level.

    glottolog index (family|language|dialect|all)
    """
    for level in Level:
        if args.args[0] in [level.name, 'all']:
            make_index(level, repos=args.repos)


def tree(args):
    ascii_tree(
        args.args[0],
        getattr(Level, args.args[1], None) if len(args.args) > 1 else None,
        tree=languoids_path('tree', repos=args.repos))


def missing_iso(args):
    iso = ISO(args.args[0] if args.args else None)
    changed_to = []
    for code in iso.retirements:
        changed_to.extend(code.change_to)
    changed_to = set(changed_to)

    ingl = set([l.iso for l in Glottolog(args.repos).languoids() if l.iso])
    for code in sorted(iso.languages):
        if code.type == 'Individual/Living':
            if code not in changed_to:
                if code.code not in ingl:
                    print(code, code.type)


def check_tree(args):
    iso_tables = list(args.repos.joinpath('iso639-3').glob('*.zip'))
    if iso_tables:
        log.info('Checking ISO codes against %s' % iso_tables[0].name)
        iso = ISO(iso_tables[0])
    else:
        iso = None

    glottocodes = Glottocodes()
    log.info('checking tree at %s' % args.repos)
    by_level = Counter()
    by_category = Counter()
    for lang in Glottolog(args.repos).languoids():
        by_level.update([lang.level.name])
        if lang.level == Level.language:
            by_category.update([lang.category])

        if iso and lang.iso:
            if lang.iso not in iso:
                log.warn('invalid ISO-639-3 code: %s [%s]' % (lang.id, lang.iso))
            else:
                isocode = iso[lang.iso]
                if isocode.is_retired and lang.category != 'Bookkeeping':
                    msg = '%s %s' % (lang.id, repr(isocode))
                    if len(isocode.change_to) == 1:
                        msg += ' changed to %s' % repr(isocode.change_to[0])
                    log.warn(msg)

        if not lang.id.startswith('unun9') and lang.id not in glottocodes:
            log.error('unregistered glottocode %s' % lang.id)
        for attr in ['level', 'name', 'glottocode']:
            if not getattr(lang, attr):
                log.error('missing %s: %s' % (attr, lang.id))
        if not Glottocode.pattern.match(lang.dir.name):
            log.error('invalid directory name: %s' % lang.dir.name)
        if lang.level == Level.language:
            if lang.parent and lang.parent.level != Level.family:
                log.error('invalid nesting of language under {0}: {1}'.format(
                    lang.parent.level, lang.id))
            for child in lang.children:
                if child.level != Level.dialect:
                    log.error('invalid nesting of {0} under language: {1}'.format(
                        child.level, child.id))
        elif lang.level == Level.family:
            for d in lang.dir.iterdir():
                if d.is_dir():
                    break
            else:
                log.error('family without children: {0}'.format(lang.id))

    def log_counter(counter, name):
        msg = [name + ':']
        maxl = max([len(k) for k in counter.keys()]) + 1
        for k, l in counter.most_common():
            msg.append(('{0:<%s} {1:>8,}' % maxl).format(k + ':', l))
        msg.append(('{0:<%s} {1:>8,}' % maxl).format('', sum(list(counter.values()))))
        log.info('\n'.join(msg))

    log_counter(by_level, 'Languoids by level')
    log_counter(by_category, 'Languages by category')
    return by_level


def recode(args):
    """Assign a new glottocode to an existing languoid.

    glottolog recode <code>
    """
    lang = find_languoid(glottocode=args.args[0])
    if not lang:
        raise ParserError('languoid not found')
    lang.id = Glottocode.from_name(lang.name)
    new_dir = lang.dir.parent.joinpath(lang.id)
    copytree(lang.dir, new_dir)
    lang.write_info(new_dir)
    remove(new_dir.joinpath('%s.ini' % args.args[0]))
    rmtree(lang.dir)
    print("%s -> %s" % (args.args[0], lang.id))


def new_languoid(args):
    """Create a new languoid directory for a languoid specified by name and level.

    glottolog new_languoid <name> <level>
    """
    assert args.args[1] in ['family', 'language', 'dialect']
    lang = Languoid.from_name_id_level(
        args.args[0],
        Glottocode.from_name(args.args[0]),
        args.args[1],
        **dict(prop.split('=') for prop in args.args[2:]))
    #
    # FIXME: how to specify parent? Just mv there?
    #
    print("Info written to %s" % lang.write_info())


def tree2lff(args, **test_kw):
    """Create lff.txt and dff.txt from the current languoid tree.

    glottolog tree2lff
    """
    lff.tree2lff(tree=languoids_path('tree', repos=args.repos), **test_kw)


def lff2tree(args):
    """Recreate tree from lff.txt and dff.txt

    glottolog lff2tree [test]
    """
    lff.lff2tree()
    if args.args and args.args[0] == 'test':
        print("""
You can run

    diff -rbB build/tree/ languoids/tree/

to inspect the changes in the directory tree.
""")
    else:
        print("""
Run

    git status

to inspect changes in the directory tree.
You can run

    diff -rbB build/tree/ languoids/tree/

to inspect the changes in detail.

- To discard changes run

    git checkout languoids/tree

- To commit and push changes, run

    git add -A languoids/tree/...

  for any newly created nodes listed under

# Untracked files:
#   (use "git add <file>..." to include in what will be committed)
#
#	languoids/tree/...

  followed by

    git commit -a -m"reason for change of classification"
    git push origin
""")


def search(args):
    """
    Search Glottolog references
    """
    count, results = fts.search(args.args[0], repos=args.repos)
    table = Table('ID', 'Author', 'Year', 'Title')
    print('{} matches'.format(count))
    for res in results:
        table.append([res.id, res.author, res.year, res.title])
    print(table.render(tablefmt='simple'))


def ftsindex(args):
    """
    Index monster.bib for use with the whoosh search engine.
    """
    monster = build_path('monster-utf8.bib', repos=args.repos)
    if not monster.exists():
        compile_monster(repos=args.repos)
    return fts.build_index(args.repos, monster)


def stats(args):
    ops = defaultdict(Counter)

    for l in Glottolog(args.repos).languoids():
        for sec in l.cfg:
            for opt in l.cfg[sec]:
                if l.cfg.get(sec, opt):
                    ops[sec].update([opt])

    t = Table('section', 'option', 'count')
    for section, options in ops.items():
        t.append([section, '', 0.0])
        for k, n in options.most_common():
            t.append(['', k, float(n)])
    print(t.render(condensed=False, floatfmt=',.0f'))


def classification(args):
    for l in Glottolog(args.repos).languoids():
        if l.classification_comment.family:
            print('{0} family classification: {1}'.format(l.id, l.classification_comment.family))
        if l.classification_comment.sub:
            print('{0} subclassification: {1}'.format(l.id, l.classification_comment.sub))


def main():  # pragma: no cover
    parser = ArgumentParser(
        'pyglottolog',
        stats,
        monster,
        index,
        tree2lff,
        lff2tree,
        new_languoid,
        recode,
        tree,
        missing_iso,
        check_tree,
        search,
        classification,
        ftsindex)
    parser.add_argument(
        '--repos', help="path to glottolog data repository", type=Path, default=DATA_DIR)
    sys.exit(parser.main())
