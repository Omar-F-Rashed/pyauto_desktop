from setuptools import setup, find_packages
from pathlib import Path
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()
setup(
    name='pyauto-desktop',
    version='0.3.2',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'opencv-python',
        'numpy',
        'Pillow',
        'PyQt6',
        'pynput',
        'mss',
        'pydirectinput'
    ],
    description='A desktop automation tool for image recognition.',
    long_description_content_type='text/markdown',
    long_description=long_description,
    author='Omar Rashed',
    author_email='justdev.contact@gmail.com',
    url='https://github.com/Omar-F-Rashed/pyauto-desktop',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)