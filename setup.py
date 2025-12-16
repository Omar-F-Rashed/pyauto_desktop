from setuptools import setup, find_packages

setup(
    name='pyauto-desktop',
    version='0.1.5',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'opencv-python',
        'numpy',
        'Pillow',
        'PyQt6'
    ],
    description='A lightweight desktop automation tool for image recognition.',
    author='Omar Rashed',
    author_email='justdev.contact@gmail.com',
    url='https://github.com/Omar-F-Rashed/pyauto-desktop',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)