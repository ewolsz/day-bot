# Day bot

The Day Trader skill's opening-range breakout, run hands-off on an Alpaca **paper** account from GitHub. No computer needs to be on. It costs nothing.

It is a second, separate experiment. It does not touch the rotation bot, and it must not share that bot's paper account.

**It ships switched off.** A file called `STOP` blocks all orders until you delete it. Run the backtest first.

## What it does each trading day

1. **9:45 to 10:30 AM New York:** after every 5-minute bar closes, it checks 50 large stocks.
2. **Trigger:** a stock's first 5-minute close above the high of its first 15 minutes. One trigger per stock per day.
3. **Plan, before buying:** stop at the middle of that first-15-minute range, target at 2x the risk.
4. **Size and risk check:** the smallest of four limits, then every rule in the table below. A block is final.
5. **Order:** one bracket order (buy + stop-loss + take-profit), at most 3 a day.
6. **3:52 PM:** a second job sells anything still open. Nothing is held overnight.

Phone alerts (ntfy): each buy, the end-of-day result, and anything that goes wrong.

## The settings (`config/day_bot.json`)

| setting | value | where it comes from |
| --- | --- | --- |
| Budget | $5,000 | skill default |
| Max loss per trade | $50 (1% of the budget) | skill default |
| Max loss per day | $150 (3%) | skill default |
| Max trades per day | 3 | skill default |
| Minimum reward:risk | 1.0 | skill default |
| Cash always kept back | 10% | skill default |
| Opening range | first 15 minutes, 5-minute bars | skill default |
| Stop | opening-range midpoint | skill default for this setup |
| Target | 2x the risk | skill's exit default |
| Flat by | 3:55 PM | skill default |
| Long only, no margin, no options, whole shares | yes | skill default |
| Biggest position | 30% of the budget ($1,500) | **changed** from 75%, so 3 trades can be open at once |
| Last entry | 10:30 AM | **changed** from 3:30 PM: an opening-range breakout is a morning setup, and a short session stays inside GitHub's free minutes |
| Stock list | 50 large, heavily traded stocks | **changed** from "scan ~5,900 and you pick": a bot needs a fixed list, and thin stocks fill badly |
| Halt | no new trades once the account is under $4,250 (15% down) | **added** |
| Early-close days | sits out | **added** |
| Your "yes" before each order | removed | **changed**: only acceptable because the bot cannot trade real money |

Because the position cap usually decides the size, a typical trade risks about $10 to $25, well under the $50 limit.

Do not change settings while a test is running. Changing them after seeing results turns the test into curve-fitting.

## Setup (about 20 minutes, once)

**1. A separate paper account in Alpaca**
1. Log in at alpaca.markets. Click the account name at the top left.
2. Choose **Open New Paper Account**. Name it `day-bot` and set the starting amount to **5000**.
3. Switch to that new account, find **API Keys**, click **Generate**, and copy the Key and the Secret into a note. The Secret is shown once.

Your rotation bot keeps its own account and keys. Nothing changes there.

**2. A new private repository on GitHub**
1. github.com, **+** at the top right, **New repository**. Name: `day-bot`. Choose **Private**. Create it.
2. Click **uploading an existing file**.
3. Unzip `day-bot.zip` on your Mac and open the `day-bot` folder. Press **Cmd + Shift + .** so the hidden `.github` folder shows.
4. Select **everything inside** the folder and drag it onto the GitHub page. Click **Commit changes**.
5. The repository's main page should show: `.github/workflows`, `bot`, `config`, `scripts`, `tests`, `README.md`, `STOP`.

**3. Three secrets**
Settings, Secrets and variables, Actions, **New repository secret**:
- `ALPACA_KEY`: the new account's Key
- `ALPACA_SECRET`: the new account's Secret
- `NTFY_TOPIC`: the same ntfy topic your rotation bot uses

**4. Check the connection**
Actions, **Day bot**, Run workflow, mode **status**, Run workflow. Open the run. It should show equity $5,000.00 and no positions. If it says WRONG ACCOUNT, the keys are the rotation bot's.

**5. Run the backtest**
Actions, **Day bot backtest**, Run workflow, part **explore**. It takes 15 to 30 minutes. The result table is on the run's page. Send it to Claude before going further.

**6. Switch it on (paper)**
Open the file `STOP` in the repository, click the **...** menu, **Delete file**, Commit. From the next trading morning the bot trades the paper account on its own.

## Living with it

- **Pause:** add a file called `STOP` again (Add file, Create new file, name it `STOP`, Commit).
- **Sell everything now:** Actions, Day bot flatten, Run workflow, tick the box.
- **Results:** Actions, Day bot report, Run workflow. The table is on the run's page.
- **Judge it after about 100 trades,** not before. That is a few months.
- **Free minutes:** a private repository gets 2,000 GitHub Actions minutes a month. This bot uses roughly 1,000 to 1,300, and the rotation bot a little. If GitHub ever warns you about minutes, tell Claude.

## What has and has not been checked

Checked, offline, by the 45 tests in `tests/`:
- The rules reproduce the skill's own worked example to the cent (TSLA, Oct 19 2026: range 354.47 to 362.18, trigger 10:15 AM at 364.18, stop 358.32, 8 shares on the skill's settings) and the skill's 59-session history (33 trades: 13 target, 15 stop, 5 neither).
- Sizing, every risk limit, the entry window, stale triggers, the wrong-account guard, flattening, the report.

Not checked, because it needs your keys and a live market:
- The first real conversation with Alpaca. Step 4 (status) and a **dry-run** during market hours are the test. Expect the first live morning to need a look.
- GitHub can start scheduled jobs late. A late morning start only misses early bars. A late flatten is covered: stops and targets stay in place overnight, the bot alerts you, and it sells at the next open.

Known gaps between backtest and live: the backtest uses full-market data and bar-close fills; the live bot sees one exchange (IEX) and gets market fills.

## Honest expectations

- The skill's own example calls this setup "close to a coin flip". On the one stock of sample data available offline (TSLA, 60 days, 26 trades) this bot's version lost about 0.2 R a trade. That sample is far too small to mean anything, which is why the backtest exists.
- With about $10 to $25 at risk per trade, even a good result will be small in dollars and is very unlikely to beat simply holding an index fund. That check is in the pass mark on purpose.
- Most people who day trade lose money. This is not financial advice, and the bot has not earned any real money.

## Files

```
bot/rules.py            the trading rules (shared by the bot and the backtest)
bot/day_bot.py          run, flatten, status, report
scripts/orb_study.py    the backtest and its pass mark
config/day_bot.json     every setting and the stock list
tests/                  45 offline tests; fixtures from the skill (MIT, Jake Schincariol)
.github/workflows/      the four schedules
STOP                    the off switch
```
