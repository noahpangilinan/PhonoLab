r"""Praat's backslash codes for special symbols, e.g. ``\ae`` -> æ, ``\sw`` -> ə.

Generated from Praat 7.0.02 ("TextGrid: Convert to Unicode") by packaging/generate_ipa.py, trying every
backslash + two-character code; tests/test_ipa.py checks it still agrees with Praat.
"""

from __future__ import annotations

import re

TRIGRAPHS: dict[str, str] = {
    "\\!d": "\xa1",  # inverted exclamation mark
    "\\''": "\u030b",  # combining double acute accent
    "\\'-": "\u1dc7",  # combining acute-macron
    "\\'1": "\u02c8",  # modifier letter vertical line
    "\\'2": "\u02cc",  # modifier letter low vertical line
    "\\'^": "\u0301",  # combining acute accent
    "\\'p": "\u2032",  # prime
    "\\+-": "\xb1",  # plus-minus sign
    "\\+v": "\u031f",  # combining plus sign below
    "\\-'": "\u1dc4",  # combining macron-acute
    "\\--": "\u2013",  # en dash
    "\\-/": "\u0336",  # combining long stroke overlay
    "\\-1": "\u02e9",  # modifier letter extra-low tone bar
    "\\-2": "\u02e8",  # modifier letter low tone bar
    "\\-3": "\u02e7",  # modifier letter mid tone bar
    "\\-4": "\u02e6",  # modifier letter high tone bar
    "\\-5": "\u02e5",  # modifier letter extra-high tone bar
    "\\->": "\u2192",  # rightwards arrow
    "\\-^": "\u0304",  # combining macron
    "\\-`": "\u1dc6",  # combining macron-grave
    "\\-h": "\xad",  # soft hyphen
    "\\-m": "\u2212",  # minus sign
    "\\-v": "\u0320",  # combining minus sign below
    "\\..": "\u22ef",  # midline horizontal ellipsis
    "\\.3": "\u2234",  # therefore
    "\\.c": "\xb7",  # middle dot
    "\\.f": "\u02d1",  # modifier letter half triangular colon
    "\\.v": "\u0323",  # combining dot below
    "\\//": "\u0338",  # combining long solidus overlay
    "\\/d": "\u2215",  # division slash
    "\\0^": "\u030a",  # combining ring above
    "\\0v": "\u0325",  # combining ring below
    "\\3v": "\u0339",  # combining right half ring below
    "\\9+": "\u05e2",  # hebrew letter ayin
    "\\9-": "\u02a2",  # latin letter reversed glottal stop with stroke
    "\\9e": "\u0295",  # latin letter pharyngeal voiced fricative
    "\\:-": "\xf7",  # division sign
    "\\:^": "\u0308",  # combining diaeresis
    "\\:f": "\u02d0",  # modifier letter triangular colon
    "\\:v": "\u0324",  # combining diaeresis below
    "\\<-": "\u2190",  # leftwards arrow
    "\\<<": "\xab",  # left-pointing double angle quotation mark
    "\\<=": "\u21d0",  # leftwards double arrow
    "\\<>": "\u2194",  # left right arrow
    "\\<_": "\u2264",  # less-than or equal to
    "\\=/": "\u2260",  # not equal to
    "\\=3": "\u2261",  # identical to
    "\\=>": "\u21d2",  # rightwards double arrow
    "\\=~": "\u2245",  # approximately equal to
    "\\>>": "\xbb",  # right-pointing double angle quotation mark
    "\\>_": "\u2265",  # greater-than or equal to
    "\\?+": "\u05d0",  # hebrew letter alef
    "\\?-": "\u02a1",  # latin letter glottal stop with stroke
    "\\?d": "\xbf",  # inverted question mark
    "\\?g": "\u0294",  # latin letter glottal stop
    "\\A'": "\xc1",  # latin capital letter a with acute
    "\\A;": "\u0104",  # latin capital letter a with ogonek
    "\\A^": "\xc2",  # latin capital letter a with circumflex
    "\\A`": "\xc0",  # latin capital letter a with grave
    "\\Ae": "\xc6",  # latin capital letter ae
    "\\Al": "\u0391",  # greek capital letter alpha
    "\\Ao": "\xc5",  # latin capital letter a with ring above
    "\\At": "\u2200",  # for all
    "\\A~": "\xc3",  # latin capital letter a with tilde
    "\\B+": "\u05d1",  # hebrew letter bet
    "\\Be": "\u0392",  # greek capital letter beta
    "\\C%": "\u05e5",  # hebrew letter final tsadi
    "\\C'": "\u0106",  # latin capital letter c with acute
    "\\C+": "\u05e6",  # hebrew letter tsadi
    "\\C,": "\xc7",  # latin capital letter c with cedilla
    "\\C<": "\u010c",  # latin capital letter c with caron
    "\\Ci": "\u03a7",  # greek capital letter chi
    "\\D+": "\u05d3",  # hebrew letter dalet
    "\\D-": "\u0110",  # latin capital letter d with stroke
    "\\D<": "\u010e",  # latin capital letter d with caron
    "\\De": "\u0394",  # greek capital letter delta
    "\\Dv": "\u033b",  # combining square below
    "\\E'": "\xc9",  # latin capital letter e with acute
    "\\E;": "\u0118",  # latin capital letter e with ogonek
    "\\E<": "\u011a",  # latin capital letter e with caron
    "\\E^": "\xca",  # latin capital letter e with circumflex
    "\\E`": "\xc8",  # latin capital letter e with grave
    "\\Ep": "\u0395",  # greek capital letter epsilon
    "\\Er": "\u2203",  # there exists
    "\\Et": "\u0397",  # greek capital letter eta
    "\\FI": "\ufb01",  # latin small ligature fi
    "\\FL": "\ufb02",  # latin small ligature fl
    "\\Fi": "\u03a6",  # greek capital letter phi
    "\\G+": "\u05d2",  # hebrew letter gimel
    "\\G<": "\u01e6",  # latin capital letter g with caron
    "\\G^": "\u029b",  # latin letter small capital g with hook
    "\\Ga": "\u0393",  # greek capital letter gamma
    "\\H+": "\u05d4",  # hebrew letter he
    "\\I'": "\xcd",  # latin capital letter i with acute
    "\\I^": "\xce",  # latin capital letter i with circumflex
    "\\I`": "\xcc",  # latin capital letter i with grave
    "\\Io": "\u0399",  # greek capital letter iota
    "\\J+": "\u05d9",  # hebrew letter yod
    "\\K%": "\u05da",  # hebrew letter final kaf
    "\\K+": "\u05db",  # hebrew letter kaf
    "\\Ka": "\u039a",  # greek capital letter kappa
    "\\L+": "\u05dc",  # hebrew letter lamed
    "\\L/": "\u0141",  # latin capital letter l with stroke
    "\\LI": "\u035c",  # combining double breve below
    "\\La": "\u039b",  # greek capital letter lamda
    "\\Lp": "\xa3",  # pound sign
    "\\M%": "\u05dd",  # hebrew letter final mem
    "\\M+": "\u05de",  # hebrew letter mem
    "\\Mu": "\u039c",  # greek capital letter mu
    "\\N%": "\u05df",  # hebrew letter final nun
    "\\N'": "\u0143",  # latin capital letter n with acute
    "\\N+": "\u05e0",  # hebrew letter nun
    "\\N<": "\u0147",  # latin capital letter n with caron
    "\\NE": "\u2197",  # north east arrow
    "\\NW": "\u2196",  # north west arrow
    "\\N^": "\u0306",  # combining breve
    "\\Nu": "\u039d",  # greek capital letter nu
    "\\Nv": "\u032a",  # combining bridge below
    "\\N~": "\xd1",  # latin capital letter n with tilde
    "\\O'": "\xd3",  # latin capital letter o with acute
    "\\O.": "\u0298",  # latin letter bilabial click
    "\\O/": "\xd8",  # latin capital letter o with stroke
    "\\O:": "\u0150",  # latin capital letter o with double acute
    "\\O^": "\xd4",  # latin capital letter o with circumflex
    "\\O`": "\xd2",  # latin capital letter o with grave
    "\\Oe": "\u0276",  # latin letter small capital oe
    "\\Om": "\u03a9",  # greek capital letter omega
    "\\On": "\u039f",  # greek capital letter omicron
    "\\O|": "\u2205",  # empty set
    "\\O~": "\xd5",  # latin capital letter o with tilde
    "\\P%": "\u05e3",  # hebrew letter final pe
    "\\P+": "\u05e4",  # hebrew letter pe
    "\\Pi": "\u03a0",  # greek capital letter pi
    "\\Ps": "\u03a8",  # greek capital letter psi
    "\\Q+": "\u05e7",  # hebrew letter qof
    "\\R+": "\u05e8",  # hebrew letter resh
    "\\R<": "\u0158",  # latin capital letter r with caron
    "\\Ro": "\u03a1",  # greek capital letter rho
    "\\S'": "\u015a",  # latin capital letter s with acute
    "\\S+": "\u05e1",  # hebrew letter samekh
    "\\S,": "\u015e",  # latin capital letter s with cedilla
    "\\S<": "\u0160",  # latin capital letter s with caron
    "\\SE": "\u2198",  # south east arrow
    "\\SS": "\xa7",  # section sign
    "\\SW": "\u2199",  # south west arrow
    "\\Si": "\u03a3",  # greek capital letter sigma
    "\\T(": "\u0318",  # combining left tack below
    "\\T)": "\u0319",  # combining right tack below
    "\\T+": "\u05ea",  # hebrew letter tav
    "\\T,": "\u0162",  # latin capital letter t with cedilla
    "\\T<": "\u0164",  # latin capital letter t with caron
    "\\TM": "\u2122",  # trade mark sign
    "\\T^": "\u031d",  # combining up tack below
    "\\Ta": "\u03a4",  # greek capital letter tau
    "\\Te": "\u0398",  # greek capital letter theta
    "\\Th": "\xde",  # latin capital letter thorn
    "\\Tt": "\u22a5",  # up tack
    "\\Tv": "\u031e",  # combining down tack below
    "\\U'": "\xda",  # latin capital letter u with acute
    "\\U:": "\u0170",  # latin capital letter u with double acute
    "\\U^": "\xdb",  # latin capital letter u with circumflex
    "\\U`": "\xd9",  # latin capital letter u with grave
    "\\Uo": "\u016e",  # latin capital letter u with ring above
    "\\Up": "\u03a5",  # greek capital letter upsilon
    "\\Uv": "\u033a",  # combining inverted bridge below
    "\\V+": "\u05d5",  # hebrew letter vav
    "\\V^": "\u2c71",  # latin small letter v with right hook
    "\\Vr": "\u221a",  # square root
    "\\W+": "\u05e9",  # hebrew letter shin
    "\\X+": "\u05d7",  # hebrew letter het
    "\\Xi": "\u039e",  # greek capital letter xi
    "\\Y'": "\xdd",  # latin capital letter y with acute
    "\\Y+": "\u05d8",  # hebrew letter tet
    "\\Y=": "\xa5",  # yen sign
    "\\Z!": "\u017b",  # latin capital letter z with dot above
    "\\Z'": "\u0179",  # latin capital letter z with acute
    "\\Z+": "\u05d6",  # hebrew letter zayin
    "\\Z<": "\u017d",  # latin capital letter z with caron
    "\\Ze": "\u0396",  # greek capital letter zeta
    "\\^#": "\u21d1",  # upwards double arrow
    "\\^9": "\u02c1",  # modifier letter reversed glottal stop
    "\\^?": "\u02c0",  # modifier letter glottal stop
    "\\^G": "\u1dad",  # modifier letter small turned m with long leg
    "\\^H": "\u02b1",  # modifier letter small h with hook
    "\\^M": "\u1d5a",  # modifier letter small turned m
    "\\^N": "\u1d51",  # modifier letter small eng
    "\\^Y": "\u1da3",  # modifier letter small turned h
    "\\^^": "\u0302",  # combining circumflex accent
    "\\^f": "\u1da0",  # modifier letter small f
    "\\^g": "\u02e0",  # modifier letter small gamma
    "\\^h": "\u02b0",  # modifier letter small h
    "\\^j": "\u02b2",  # modifier letter small j
    "\\^l": "\u02e1",  # modifier letter small l
    "\\^m": "\u1d50",  # modifier letter small m
    "\\^n": "\u207f",  # superscript latin small letter n
    "\\^s": "\u02e2",  # modifier letter small s
    "\\^w": "\u02b7",  # modifier letter small w
    "\\^x": "\u02e3",  # modifier letter small x
    "\\^y": "\u02b8",  # modifier letter small y
    "\\^|": "\u2191",  # upwards arrow
    "\\_#": "\u21d3",  # downwards double arrow
    "\\_u": "\u203f",  # undertie
    "\\_|": "\u2193",  # downwards arrow
    "\\`-": "\u1dc5",  # combining grave-macron
    "\\`^": "\u0300",  # combining grave accent
    "\\``": "\u030f",  # combining double grave accent
    "\\a'": "\xe1",  # latin small letter a with acute
    "\\a;": "\u0105",  # latin small letter a with ogonek
    "\\a^": "\xe2",  # latin small letter a with circumflex
    "\\a_": "\xaa",  # feminine ordinal indicator
    "\\a`": "\xe0",  # latin small letter a with grave
    "\\ab": "\u0252",  # latin small letter turned alpha
    "\\ae": "\xe6",  # latin small letter ae
    "\\al": "\u03b1",  # greek small letter alpha
    "\\an": "\u2227",  # logical and
    "\\ao": "\xe5",  # latin small letter a with ring above
    "\\ap": "\u02bc",  # modifier letter apostrophe
    "\\as": "\u0251",  # latin small letter alpha
    "\\at": "\u0250",  # latin small letter turned a
    "\\ay": "\u0252",  # latin small letter turned alpha
    "\\a~": "\xe3",  # latin small letter a with tilde
    "\\b^": "\u0253",  # latin small letter b with hook
    "\\bc": "\u0299",  # latin letter small capital b
    "\\be": "\u03b2",  # greek small letter beta
    "\\bf": "\u03b2",  # greek small letter beta
    "\\bu": "\u2022",  # bullet
    "\\c'": "\u0107",  # latin small letter c with acute
    "\\c,": "\xe7",  # latin small letter c with cedilla
    "\\c/": "\xa2",  # cent sign
    "\\c<": "\u010d",  # latin small letter c with caron
    "\\c=": "\u2282",  # subset of
    "\\cE": "\u05b5",  # hebrew point tsere
    "\\cc": "\u0255",  # latin small letter c with curl
    "\\cf": "\u03c7",  # greek small letter chi
    "\\ci": "\u03c7",  # greek small letter chi
    "\\cl": "\u2663",  # black club suit
    "\\cn": "\u031a",  # combining left angle above
    "\\co": "\xa9",  # copyright sign
    "\\ct": "\u0254",  # latin small letter open o
    "\\cu": "\xa4",  # currency sign
    "\\cv": "\u031c",  # combining left half ring below
    "\\d-": "\u0111",  # latin small letter d with stroke
    "\\d.": "\u0256",  # latin small letter d with tail
    "\\d<": "\u010f",  # latin small letter d with caron
    "\\dZ": "\u02a4",  # latin small letter dezh digraph
    "\\d^": "\u0257",  # latin small letter d with hook
    "\\dd": "\u2202",  # partial differential
    "\\de": "\u03b4",  # greek small letter delta
    "\\dg": "\xb0",  # degree sign
    "\\dh": "\xf0",  # latin small letter eth
    "\\di": "\u2666",  # black diamond suit
    "\\dq": "\u05bc",  # hebrew point dagesh or mapiq
    "\\dz": "\u02a3",  # latin small letter dz digraph
    "\\e'": "\xe9",  # latin small letter e with acute
    "\\e-": "\u0258",  # latin small letter reversed e
    "\\e;": "\u0119",  # latin small letter e with ogonek
    "\\e<": "\u011b",  # latin small letter e with caron
    "\\e=": "\u2208",  # element of
    "\\e^": "\xea",  # latin small letter e with circumflex
    "\\e`": "\xe8",  # latin small letter e with grave
    "\\ef": "\u025b",  # latin small letter open e
    "\\ep": "\u03b5",  # greek small letter epsilon
    "\\eq": "\u21d4",  # left right double arrow
    "\\er": "\u025c",  # latin small letter reversed open e
    "\\et": "\u03b7",  # greek small letter eta
    "\\eu": "\u20ac",  # euro sign
    "\\f.": "\u027d",  # latin small letter r with tail
    "\\f2": "\u03d5",  # greek phi symbol
    "\\f5": "\u2740",  # white florette
    "\\fd": "\u0192",  # latin small letter f with hook
    "\\ff": "\u0278",  # latin small letter phi
    "\\fh": "\u027e",  # latin small letter r with fishhook
    "\\fi": "\u03c6",  # greek small letter phi
    "\\fr": "\u1dc9",  # combining acute-grave-acute
    "\\g<": "\u01e7",  # latin small letter g with caron
    "\\g^": "\u0260",  # latin small letter g with hook
    "\\ga": "\u03b3",  # greek small letter gamma
    "\\gc": "\u0262",  # latin letter small capital g
    "\\gf": "\u0263",  # latin small letter gamma
    "\\gs": "\u0261",  # latin small letter script g
    "\\h-": "\u0127",  # latin small letter h with stroke
    "\\hI": "\u05b4",  # hebrew point hiriq
    "\\hO": "\u05b9",  # hebrew point holam
    "\\h^": "\u0266",  # latin small letter h with hook
    "\\hc": "\u029c",  # latin letter small capital h
    "\\he": "\u2665",  # black heart suit
    "\\hj": "\u0267",  # latin small letter heng with hook
    "\\hr": "\u02de",  # modifier letter rhotic hook
    "\\hs": "\u028a",  # latin small letter upsilon
    "\\ht": "\u0265",  # latin small letter turned h
    "\\i'": "\xed",  # latin small letter i with acute
    "\\i-": "\u0268",  # latin small letter i with stroke
    "\\i^": "\xee",  # latin small letter i with circumflex
    "\\i`": "\xec",  # latin small letter i with grave
    "\\ic": "\u026a",  # latin letter small capital i
    "\\id": "\u027f",  # latin small letter reversed r with fishhook
    "\\in": "\u222b",  # integral
    "\\io": "\u03b9",  # greek small letter iota
    "\\ir": "\u0285",  # latin small letter squat reversed esh
    "\\j-": "\u025f",  # latin small letter dotless j with stroke
    "\\j^": "\u0284",  # latin small letter dotless j with stroke and hook
    "\\jc": "\u029d",  # latin small letter j with crossed-tail
    "\\ka": "\u03ba",  # greek small letter kappa
    "\\kb": "\u025e",  # latin small letter closed reversed open e
    "\\l-": "\u026c",  # latin small letter l with belt
    "\\l.": "\u026d",  # latin small letter l with retroflex hook
    "\\l/": "\u0142",  # latin small letter l with stroke
    "\\la": "\u03bb",  # greek small letter lamda
    "\\lc": "\u029f",  # latin letter small capital l
    "\\li": "\u0361",  # combining double inverted breve
    "\\lz": "\u026e",  # latin small letter lezh
    "\\l~": "\u026b",  # latin small letter l with middle tilde
    "\\mj": "\u0271",  # latin small letter m with hook
    "\\ml": "\u0270",  # latin small letter turned m with long leg
    "\\mt": "\u026f",  # latin small letter turned m
    "\\mu": "\u03bc",  # greek small letter mu
    "\\mv": "\u033c",  # combining seagull below
    "\\n'": "\u0144",  # latin small letter n with acute
    "\\n.": "\u0273",  # latin small letter n with retroflex hook
    "\\n<": "\u0148",  # latin small letter n with caron
    "\\nc": "\u0274",  # latin letter small capital n
    "\\ng": "\u014b",  # latin small letter eng
    "\\ni": "\u2229",  # intersection
    "\\nj": "\u0272",  # latin small letter n with left hook
    "\\no": "\xac",  # not sign
    "\\nu": "\u03bd",  # greek small letter nu
    "\\nv": "\u032f",  # combining inverted breve below
    "\\n~": "\xf1",  # latin small letter n with tilde
    "\\o'": "\xf3",  # latin small letter o with acute
    "\\o+": "\u2295",  # circled plus
    "\\o-": "\u0275",  # latin small letter barred o
    "\\o/": "\xf8",  # latin small letter o with stroke
    "\\o2": "\u03d6",  # greek pi symbol
    "\\o:": "\u0151",  # latin small letter o with double acute
    "\\o^": "\xf4",  # latin small letter o with circumflex
    "\\o_": "\xba",  # masculine ordinal indicator
    "\\o`": "\xf2",  # latin small letter o with grave
    "\\oc": "\u221d",  # proportional to
    "\\oe": "\u0153",  # latin small ligature oe
    "\\om": "\u03c9",  # greek small letter omega
    "\\on": "\u03bf",  # greek small letter omicron
    "\\oo": "\u221e",  # infinity
    "\\or": "\u2228",  # logical or
    "\\ox": "\u2297",  # circled times
    "\\o~": "\xf5",  # latin small letter o with tilde
    "\\pA": "\u05b7",  # hebrew point patah
    "\\pf": "\u261e",  # white right pointing index
    "\\pi": "\u03c0",  # greek small letter pi
    "\\ps": "\u03c8",  # greek small letter psi
    "\\qA": "\u05b8",  # hebrew point qamats
    "\\qU": "\u05bb",  # hebrew point qubuts
    "\\r.": "\u027b",  # latin small letter turned r with hook
    "\\r<": "\u0159",  # latin small letter r with caron
    "\\rc": "\u0280",  # latin letter small capital r
    "\\re": "\xae",  # registered sign
    "\\rf": "\u1dc8",  # combining grave-acute-grave
    "\\rh": "\u0264",  # latin small letter rams horn
    "\\ri": "\u0281",  # latin letter small capital inverted r
    "\\rl": "\u027a",  # latin small letter turned r with long leg
    "\\ro": "\u03c1",  # greek small letter rho
    "\\rt": "\u0279",  # latin small letter turned r
    "\\s'": "\u015b",  # latin small letter s with acute
    "\\s,": "\u015f",  # latin small letter s with cedilla
    "\\s.": "\u0282",  # latin small letter s with hook
    "\\s2": "\u03c2",  # greek small letter final sigma
    "\\s<": "\u0161",  # latin small letter s with caron
    "\\sE": "\u05b6",  # hebrew point segol
    "\\sU": "\ufb35",  # hebrew letter vav with dagesh
    "\\sh": "\u0283",  # latin small letter esh
    "\\si": "\u03c3",  # greek small letter sigma
    "\\sp": "\u2660",  # black spade suit
    "\\sr": "\u025a",  # latin small letter schwa with hook
    "\\ss": "\xdf",  # latin small letter sharp s
    "\\su": "\u2211",  # n-ary summation
    "\\sw": "\u0259",  # latin small letter schwa
    "\\t,": "\u0163",  # latin small letter t with cedilla
    "\\t.": "\u0288",  # latin small letter t with retroflex hook
    "\\t2": "\u03d1",  # greek theta symbol
    "\\t<": "\u0165",  # latin small letter t with caron
    "\\tS": "\u02a7",  # latin small letter tesh digraph
    "\\ta": "\u03c4",  # greek small letter tau
    "\\te": "\u03b8",  # greek small letter theta
    "\\tf": "\u03b8",  # greek small letter theta
    "\\th": "\xfe",  # latin small letter thorn
    "\\tm": "\u2122",  # trade mark sign
    "\\ts": "\u02a6",  # latin small letter ts digraph
    "\\u'": "\xfa",  # latin small letter u with acute
    "\\u-": "\u0289",  # latin small letter u bar
    "\\u:": "\u0171",  # latin small letter u with double acute
    "\\u^": "\xfb",  # latin small letter u with circumflex
    "\\u`": "\xf9",  # latin small letter u with grave
    "\\uo": "\u016f",  # latin small letter u with ring above
    "\\up": "\u03c5",  # greek small letter upsilon
    "\\uu": "\u222a",  # union
    "\\vO": "\ufb4b",  # hebrew letter vav with holam
    "\\v^": "\u030c",  # combining caron
    "\\vs": "\u028b",  # latin small letter v with hook
    "\\vt": "\u028c",  # latin small letter turned v
    "\\vv": "\u032c",  # combining caron below
    "\\wt": "\u028d",  # latin small letter turned w
    "\\wv": "\u032b",  # combining inverted double arch below
    "\\x^": "\u033d",  # combining x above
    "\\xi": "\u03be",  # greek small letter xi
    "\\xx": "\xd7",  # multiplication sign
    "\\y'": "\xfd",  # latin small letter y with acute
    "\\yc": "\u028f",  # latin letter small capital y
    "\\yt": "\u028e",  # latin small letter turned y
    "\\z!": "\u017c",  # latin small letter z with dot above
    "\\z'": "\u017a",  # latin small letter z with acute
    "\\z.": "\u0290",  # latin small letter z with retroflex hook
    "\\z<": "\u017e",  # latin small letter z with caron
    "\\zc": "\u0291",  # latin small letter z with curl
    "\\ze": "\u03b6",  # greek small letter zeta
    "\\zh": "\u0292",  # latin small letter ezh
    "\\|-": "\u01c2",  # latin letter alveolar click
    "\\|1": "\u01c0",  # latin letter dental click
    "\\|2": "\u01c1",  # latin letter lateral click
    "\\|d": "\ua71c",  # modifier letter raised down arrow
    "\\|u": "\ua71b",  # modifier letter raised up arrow
    "\\|v": "\u0329",  # combining vertical line below
    "\\||": "\xb6",  # pilcrow sign
    "\\~/": "\u0334",  # combining tilde overlay
    "\\~<": "\u0334",  # combining tilde overlay
    "\\~^": "\u0303",  # combining tilde
    "\\~v": "\u0330",  # combining tilde below
    "\\~~": "\u2248",  # almost equal to
}

# Several codes can share a symbol; prefer the first (alphabetical) code when converting back.
_REVERSE: dict[str, str] = {}
for _code, _char in TRIGRAPHS.items():
    _REVERSE.setdefault(_char, _code)

_TRIGRAPH_RE = re.compile("|".join(re.escape(k) for k in sorted(TRIGRAPHS, key=len, reverse=True)))


def to_unicode(text: str) -> str:
    """Replace Praat backslash codes with the symbols they stand for."""
    if "\\" not in text:
        return text
    return _TRIGRAPH_RE.sub(lambda m: TRIGRAPHS[m.group(0)], text)


def to_trigraphs(text: str) -> str:
    """Replace symbols with Praat backslash codes (for ASCII-only workflows)."""
    return "".join(_REVERSE.get(c, c) for c in text)
