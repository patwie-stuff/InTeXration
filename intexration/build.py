import configparser
import contextlib
import logging
import os
import shutil
import subprocess
import errno


@contextlib.contextmanager
def cd(dirname):
    cur_dir = os.curdir
    try:
        os.chdir(dirname)
        yield
    finally:
        os.chdir(cur_dir)


def create_dir(path):
    """Safely create a directory."""
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    return path


def empty(path, files_only):
    for content in os.listdir(path):
        content_path = os.path.join(path, content)
        try:
            os.remove(content_path)
        except OSError:
            if not files_only:
                shutil.rmtree(content_path)
        except Exception as e:
            logging.error(e)


def clean(path):
    shutil.rmtree(path)


class CompileTask:
    def __init__(self, input_dir, output_dir, name, idx, bib):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.name = name
        self.idx = idx
        self.bib = bib
        self.tex = name + '.tex'
        self.pdf = name + '.pdf'
        self.log = name + '.log'

    def _makeindex(self):
        """Make index."""
        with cd(self.input_dir):
            if subprocess.call(['makeindex', self.idx], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) != 0:
                logging.warning("Makeindex failed")

    def _bibtex(self):
        """Compile bibtex."""
        with cd(self.input_dir):
            if subprocess.call(['bibtex', self.bib], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
                logging.warning("Bibtex failed")

    def _compile(self):
        """Compile with pdflatex."""
        with cd(self.input_dir):
            if subprocess.call(['pdflatex', '-interaction=nonstopmode', self.tex], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) != 0:
                logging.warning("Compilation finished with errors")

    def _copy(self):
        """Copy the PDF and log to the output directory."""
        pdf_source_path = os.path.join(self.input_dir, self.pdf)
        pdf_dest_path = os.path.join(self.output_dir, self.pdf)
        shutil.copyfile(pdf_source_path, pdf_dest_path)
        log_source_path = os.path.join(self.input_dir, self.log)
        log_dest_path = os.path.join(self.output_dir, self.log)
        shutil.copyfile(log_source_path, log_dest_path)

    def run(self):
        logging.info("Compiling %s", self.name)
        self._compile()
        self._makeindex()
        self._bibtex()
        self._compile()
        self._copy()
        logging.info("Compiling %s finished.", self.name)


class IntexrationConfig:

    dir_key = 'dir'
    idx_key = 'idx'
    bib_key = 'bib'

    def __init__(self, path):
        if not os.path.exists(path):
            raise RuntimeError("InTeXration config file not found")
        self.parser = configparser.ConfigParser()
        self.parser.read(path)

    def names(self):
        return self.parser.sections()

    def dir(self, name):
        if self.parser.has_option(name, self.dir_key):
            return self.parser[name][self.dir_key]
        return ''

    def idx(self, name):
        if self.parser.has_option(name, self.idx_key):
            return self.parser[name][self.idx_key]
        return name + '.idx'

    def bib(self, name):
        if self.parser.has_option(name, self.bib_key):
            return self.parser[name][self.bib_key]
        return name


class IntexrationTask:

    config_name = '.intexration'

    def __init__(self, input_dir, output_dir):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.config = IntexrationConfig(os.path.join(self.input_dir, self.config_name))

    def run(self):
        logging.info("Compile task started")
        for name in self.config.names():
            task_input = os.path.join(self.input_dir, self.config.dir(name))
            CompileTask(task_input, self.output_dir, name, self.config.idx(name),
                        self.config.bib(name)).run()

    def run_only(self, name):
        if not name in self.config.names():
            raise RuntimeError("Build not in intexration config")
        task_input = os.path.join(self.input_dir, self.config.dir(name))
        CompileTask(task_input, self.output_dir, name, self.config.idx(name),
                    self.config.bib(name)).run()


class CloneTask:

    def __init__(self, root, owner, repository, commit):
        self.root = root
        self.owner = owner
        self.repository = repository
        self.commit = commit

    def url(self):
        return 'https://github.com/' + self.owner + '/' + self.repository + '.git'

    def clone_dir(self):
        path = os.path.join(self.root, self.owner, self.repository, self.commit)
        return create_dir(path)

    def _clean(self):
        empty(os.path.join(self.root, self.owner, self.repository), False)

    def _clone(self):
        """Clone repository to build dir."""
        logging.info("Cloning from %s", self.url())
        if subprocess.call(['git', 'clone',  self.url(), self.clone_dir()], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) != 0:
            raise RuntimeError("Clone failed")

    def run(self):
        self._clean()
        self._clone()


class Build:

    input_name = 'build'
    output_name = 'out'

    def __init__(self, root, owner, repository, commit):
        self.input_dir = os.path.join(root, self.input_name)
        self.output_dir = os.path.join(root, self.output_name)
        self.owner = owner
        self.repository = repository
        self.commit = commit

    def name(self):
        return self.owner+'/'+self.repository

    def run(self):
        logging.info("Build started for %s", self.name())
        clone_task = CloneTask(self.input_dir, self.owner, self.repository, self.commit)
        try:
            clone_task.run()
            IntexrationTask(clone_task.clone_dir(), self.output_dir).run()
        except RuntimeError as e:
            logging.error(e)
        finally:
            clean(clone_task.clone_dir())
        logging.info("Build finished for %s", self.name())


class CloneBuild(Build):

    def run(self):
        logging.info("Build (clone) started for %s", self.name())
        clone_task = CloneTask(self.input_dir, self.owner, self.repository,  self.commit)
        empty(os.path.join(self.output_dir, self.owner, self.repository), True)
        try:
            clone_task.run()
        except RuntimeError as e:
            logging.error(e)


class LazyBuild(Build):

    def __init__(self, root, owner, repository, name):
        self.input_dir = os.path.join(root, self.input_name)
        self.output_dir = os.path.join(root, self.output_name)
        self.repository = repository
        self.owner = owner
        self.document_name = name

    def run(self):
        logging.info("Build (lazy) started for %s", self.name())
        try:
            IntexrationTask(self.commit_dir(), self.output_dir).run_only(self.document_name)
        except Exception as e:
            logging.error(e)

    def commit_dir(self):
        dir = os.path.join(self.input_dir, self.owner, self.repository)
        commit_dirs = os.listdir(dir)
        if not len(commit_dirs) == 1:
            raise RuntimeError("Unable to determine commit directory for lazy build")
        return os.path.join(self.input_dir, self.owner, self.repository, commit_dirs[0])