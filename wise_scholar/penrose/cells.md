Cells at a phase of mitosis or meiosis, drawn with their chromosomes. A circle per cell with its equatorial plane dashed, each chromosome as two chromatids joined at a centromere, teal for paternal and brown for maternal; one or two cells per diagram, up to about six chromosomes per cell.

Types (one per `Cell`, it sets how the chromosomes are placed):
- `MitosisMetaphase`: chromosomes single file on the equatorial plane, centromeres on the line.
- `MeiosisMetaphaseI`: homologous pairs face each other across the plane.
- `MeiosisAnaphaseI`: the homologues of each pair pulled apart toward the poles.
- `MeiosisLateAnaphaseI`: each set gathered near its pole.
- `Chromosome`.

Predicates:
- `In(Chromosome, Cell)`: required for every chromosome, one cell each.
- `Homologous(Chromosome, Chromosome)`: required for every pair in a meiosis cell, one paternal and one maternal, in either order.
- `Paternal(Chromosome)`, `Maternal(Chromosome)`: colour; one of them per chromosome.
- `Short(Chromosome)`: a short chromosome; the default is long.

Labels: `Label k "text"` puts a title under a cell, in the learner's language.

Example, mitosis beside meiosis I in a 2n = 4 cell:

```
MitosisMetaphase M
Chromosome a1, a2, b1, b2
In(a1, M)
In(a2, M)
In(b1, M)
In(b2, M)
Paternal(a1)
Maternal(a2)
Paternal(b1)
Maternal(b2)
Short(b1)
Short(b2)

MeiosisMetaphaseI K
Chromosome c1, c2, d1, d2
In(c1, K)
In(c2, K)
In(d1, K)
In(d2, K)
Paternal(c1)
Maternal(c2)
Paternal(d1)
Maternal(d2)
Short(d1)
Short(d2)
Homologous(c1, c2)
Homologous(d1, d2)

Label M "Mitosis: metaphase"
Label K "Meiosis: metaphase I"
```
