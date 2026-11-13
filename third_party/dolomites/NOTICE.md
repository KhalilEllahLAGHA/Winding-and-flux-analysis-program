# Dolomites / Koil

`koil.py` is an unmodified copy from Luigi Alberti's Dolomites project:
https://gitlab.com/LuigiAlberti/dolomites-python

Pinned revision: `21eceabcdf09ecd0873b693cfa123b3567d6f62b`.
Source: `dolomites/koil.py` at that revision.

Dolomites is copyright (C) 2006–2026 L. Alberti and contributors, University of
Padova, and distributed under GNU GPL version 3. The complete licence is in
`LICENSE`. See upstream README for contributor credits.

The application adapter in `core/connection_matrix.py` uses the upstream
star-of-slots, feasibility, coil-throw and coil-population logic. It replaces
strict sector membership tests with periodic half-open membership: this fixes
wrap-around sectors and floating-point boundary omissions, especially with even
phase counts. It rejects invalid/incomplete/unbalanced layouts instead of
silently falling back from single to double layer. Physical top/bottom coil
sides are retained; they are not independently normalised per phase.
