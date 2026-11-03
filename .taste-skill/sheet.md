# APP SHEET — Data terminal
seed 688838190 · drawn 2026-11-03 · kind commerce · dark
Brief: 편의점 점주가 하루 한 번 보는 매출 홈: 오늘 매출이 평소와 같은지, 확인할 사항, AI 제안, 내일 예상 매출

This is the style for this product. Adopt it whole and keep its move intact; everything the sheet does not fix comes from the
shared defaults in references/app-screens.md. Redraw only for a reason you can state (it contradicts the brand, or the product is
used in a way the style does not suit) and say why in your report. The values were measured on real product screens: use them
as given rather than rounding them towards your habits.

## 1. The style
A research or monitoring screen read in long sessions: cards darker than the ground, tabular digits that stack, signs instead of colour, and every selection marked by the same 1px accent line.

**The move:** Every selection (tab, toggle, range, nav item) is a 1px accent line exactly as wide as its label, placed on the nearest existing edge; numbers stay white or grey and carry their sign in the text ('+$24,000,000').

**Colour budget:** under 3%; the accent is never more than a 1px line.
**Off-style here:** filled pill tabs or a coloured segmented control; a chart with no scale and no dates (the studied screen had none and was flagged); tertiary text under 4.5:1 (#4c4c4f read at about 2:1 in the study); lighter cards with borders and a glow; green and red on every number; the one column whose job is "what moved today" and a negative headline figure may carry the polarity colours.
Distilled from 1 screen: a stock research view. Keep it narrow.. The studied screen's muted grey #82848a and red #d4405d were lifted to #8a8c92 and #e5566f so text passes 4.5:1 on the card. Its card list rows sit on a 28px pitch and its table rows on 42px.

**Its face.** Choose one of these (or one of your own of the same weight) before you build, write it in your notes next to
the screen's question, and check that it shows on the first screen. Without one the screen reads as a well-applied kit.
- Every figure in a monospace as the style's decision (IBM Plex Mono or JetBrains Mono for each price, count and time, digits that stack), with the text in Public Sans. Lint and the inspector flag mono; give the reason in the report.
- The one accent line from the product's world in place of the dealt blue (the exchange's or the team's hue): still the only selection mark, never violet or indigo.
- A signature of the market or the system as the lead: an order book's depth as two mirrored bar lists, an incident as a minute-by-minute strip, a region map with the list beside it.

## 2. Tokens
Kept from the brand: map its colours onto this style's roles (ground, surface, raised, border, rule, control, text, muted, accent, status pills, chart) and keep its proportions: under 3%; the accent is never more than a 1px line. Take the sizes, radii, row and control heights from the style as they are.

## 4. Shell — Icon rail
An unlabelled rail of 50-60px carries the brand mark at the top and 15-18px outline icons on a 34-49px pitch; groups are split by 20px hairlines, utilities sit at the bottom. The rail sits on the page ground with a 1px edge, or is white with a faint 4px shadow on a grey ground. It saves about 180px of width against a labelled sidebar, so it suits products with few destinations and screens that need the width. Icons need tooltips and an accessible name.
Numbers: railWidth 50-60, median 55; icon 15-18px outline; pitch 34-49; active icon colour alone, or a full-bleed 50px band at a 2% tint, or a 1px accent bar on the rail's border; groups short 20px hairlines, no labels; utilities pushed to the bottom after a gap of about 200px.
On a phone: The rail becomes a bottom bar with the same four or five icons, each with a short label under it.

## 5. Screens

### overview — KPIs as the chart's tabs
One card per subject, 8-16px apart: the main chart card runs full width, and any card holding a table of five columns or fewer, or a short list, pairs with its neighbour in two columns, the page header indented by the card padding so the title, the card titles, the numbers and the plot share one left edge. Balances that do not change during the day go first, in one container split by 1px dividers into equal columns; a zero balance is grey and its caption becomes the next step. In the main card, 2-4 KPIs sit in a row and act as the chart's series tabs: the selected one carries a 2px rule and an ink label, the others keep a grey label and their value in ink at a lighter weight (a grey value reads as disabled); when the tabs are the per-entity breakdown the brief asks for (takings by shop), nothing is greyed and the rule alone marks the selection. Choosing one swaps the series. Under them, one line chart as wide as the card's content (about 1136x220 in the study): 3-4 solid 1px gridlines, 4-6 round y ticks at 12px, a 2-3px line in ink with straight segments and no fill, an 8px hover dot with a 1px dashed guide and the line after the cursor in pale grey. Close with a 2-3 row comparison table on a 36px pitch, value and change columns right-aligned under a 14px grey header such as 'vs prior Monday'.
On a phone: KPI tabs become a 2-up grid above the chart, with the selected cell marked by a fill (never an underline floating inside the grid) or a row of tabs that scrolls sideways; the chart is full width, 160-200px tall, with 4 x labels; the comparison table keeps its two right-aligned columns.

## 6. Always
Real data for this product, written before the markup: names, amounts that add up, dates in order, units on every figure,
honest zeros and dashes. One chart answers one question. No gradients, glows, glass, icons in tinted squares, sparklines on KPIs,
rainbow charts, emoji, lorem or Acme. `<skill>/assets/app.css` and `<skill>/assets/charts.js` are a neutral start set to these
rules. Check with `node <skill>/scripts/lint.mjs <files>` and `node <skill>/scripts/inspect.mjs <page>`: this sheet switches both
to app rules.

Saved to .taste-skill/app/direction.json · reprint with `node draw.mjs --show`
