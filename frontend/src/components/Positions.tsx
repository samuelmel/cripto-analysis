import { Check, CurrencyDollar, Plus, Receipt, ShieldWarning, Tag, Trash, TrendDown, X } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError, addPurchase, deletePosition, registerSale } from "../data/api";
import { REASON_TEXT, coinName, fmt, parseAmount, signTone, toInput, todayIso } from "../data/analytics";
import type { ClosedPosition, DailySignal, Position } from "../types/signals";
import { CoinLabel, CoinLogo } from "./CoinLabel";
import { REASON_ICON } from "./icons";
import { Badge, Block, Button, Field, TEXT_TONE, Table, cell, inputClass, numCell } from "./ui";

const errorText = (err: unknown): string => (err instanceof ApiError || err instanceof Error ? err.message : String(err));

/* ---------- registrar compra ---------- */

export function PurchaseForm({ coins, onSaved, onCancel }: {
  readonly coins: readonly DailySignal[];
  readonly onSaved: () => Promise<void>;
  readonly onCancel: () => void;
}) {
  const [symbol, setSymbol] = useState<string>(coins[0]?.symbol ?? "BTC/USDT");
  const current = coins.find((c) => c.symbol === symbol);
  const [price, setPrice] = useState<string>(current === undefined ? "" : toInput(current.close));
  const [qty, setQty] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const priceN = parseAmount(price);
  const qtyN = parseAmount(qty);
  const total = priceN !== null && qtyN !== null ? priceN * qtyN : null;

  const pick = (s: string): void => {
    setSymbol(s);
    const c = coins.find((x) => x.symbol === s);
    if (c !== undefined) setPrice(toInput(c.close));
  };

  const submit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    if (priceN === null || qtyN === null) {
      setError("Preencha o preço pago e a quantidade com números maiores que zero.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addPurchase({ symbol, price: priceN, qty: qtyN, date });
      await onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Block>
      <form onSubmit={(e) => void submit(e)} noValidate>
        <h3 className="flex items-center gap-2 text-lg font-semibold"><Receipt size={22} aria-hidden /> Registrar uma compra</h3>
        <fieldset className="mt-4">
          <legend className="text-[13px] font-medium text-muted">Qual moeda você comprou?</legend>
          <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
            {coins.map((c) => {
              const active = c.symbol === symbol;
              return (
                <button
                  key={c.symbol}
                  type="button"
                  aria-pressed={active}
                  onClick={() => pick(c.symbol)}
                  className={`flex items-center gap-2 rounded-sm border px-2 py-2 text-left text-[14px] transition-colors ${
                    active ? "border-signal bg-signal-bg font-medium" : "border-hairline bg-surface hover:bg-ground"
                  }`}
                >
                  <CoinLogo symbol={c.symbol} size={20} />
                  {coinName(c.symbol)}
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <Field label="Preço pago por unidade (US$)" {...(current === undefined ? {} : { hint: `Último fechamento: ${fmt.price(current.close)}` })}>
            <input className={inputClass} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} aria-invalid={price !== "" && priceN === null} required />
          </Field>
          <Field label="Quantidade comprada" hint="Ex.: 0,01 para um centésimo de moeda">
            <input className={inputClass} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="0,01" aria-invalid={qty !== "" && qtyN === null} required />
          </Field>
          <Field label="Data da compra">
            <input className={inputClass} type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>

        <p className="mt-4 text-muted">
          Total investido: <strong className="num font-medium text-ink">{fmt.usd(total)}</strong>
        </p>
        {error !== null && <p role="alert" className="mt-3 text-critical">{error}</p>}

        <div className="mt-5 flex flex-wrap gap-3">
          <Button type="submit" variant="primary" busy={busy} icon={<Check size={18} aria-hidden />}>
            {busy ? "Salvando…" : `Registrar compra de ${coinName(symbol)}`}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancelar</Button>
        </div>
      </form>
    </Block>
  );
}

/* ---------- ficha de uma posição ---------- */

function Fact({ icon, label, value }: { readonly icon: ReactNode; readonly label: string; readonly value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-hairline py-2 text-[14px]">
      <dt className="flex items-center gap-2 text-muted">{icon}{label}</dt>
      <dd className="num whitespace-nowrap text-right">{value}</dd>
    </div>
  );
}

type CardMode = "view" | "sell" | "delete";

function PositionCard({ p, onChanged }: { readonly p: Position; readonly onChanged: () => Promise<void> }) {
  const [mode, setMode] = useState<CardMode>("view");
  const [salePrice, setSalePrice] = useState<string>(p.last_close === null ? "" : toInput(p.last_close));
  const [saleDate, setSaleDate] = useState<string>(todayIso());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sell = p.action === "VENDER";
  const ReasonIcon = p.reason === null ? null : REASON_ICON[p.reason];

  const run = async (action: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };

  const confirmSale = (e: FormEvent): void => {
    e.preventDefault();
    const price = parseAmount(salePrice);
    if (price === null) {
      setError("Informe o preço de venda.");
      return;
    }
    void run(() => registerSale(p.position_id, { price, date: saleDate }));
  };

  return (
    <article className="rounded-md border border-hairline bg-surface p-6" aria-label={`Posição em ${coinName(p.symbol)}`}>
      <div className="flex items-start justify-between gap-4">
        <CoinLabel symbol={p.symbol} detailed size={36} />
        {sell ? <Badge tone="critical">Vender</Badge> : <Badge tone="good">Segurar</Badge>}
      </div>
      <p className="mt-1 text-[13px] text-muted">{fmt.num(p.qty, 4)} unidades compradas em {fmt.day(p.entry_ts)}</p>

      <p className={`mt-4 text-[32px] font-medium leading-tight ${TEXT_TONE[signTone(p.return_pct)]}`}>
        {fmt.pct(p.return_pct)} <span className="text-lg">{fmt.usd(p.pnl_usd)}</span>
      </p>
      <p className="mt-2 flex gap-2 text-muted">
        {ReasonIcon !== null && <ReasonIcon size={20} className="mt-0.5 shrink-0 text-critical" aria-hidden />}
        <span>
          {sell && p.reason !== null
            ? `${REASON_TEXT[p.reason].replace(/^./, (c) => c.toUpperCase())} (desde ${fmt.day(p.signal_ts)}).`
            : "Nenhuma regra de venda disparou. A moeda segue em tendência de alta: pode continuar com ela."}
        </span>
      </p>

      <dl className="mt-4">
        <Fact icon={<CurrencyDollar size={16} aria-hidden />} label="Você pagou" value={fmt.price(p.entry_price)} />
        <Fact icon={<Tag size={16} aria-hidden />} label="Preço hoje" value={fmt.price(p.last_close)} />
        <Fact
          icon={<TrendDown size={16} aria-hidden />}
          label="Vender se fechar o dia abaixo de"
          value={fmt.price(p.sell_below_price)}
        />
        {p.stop_price !== null && (
          <Fact icon={<ShieldWarning size={16} aria-hidden />} label="Limite de perda: vender se cair a" value={fmt.price(p.stop_price)} />
        )}
      </dl>

      {mode === "view" && (
        <div className="mt-5 flex flex-wrap gap-3">
          <Button variant={sell ? "primary" : "secondary"} icon={<Check size={18} aria-hidden />} onClick={() => setMode("sell")}>
            Já vendi
          </Button>
          <Button variant="ghost" icon={<Trash size={18} aria-hidden />} onClick={() => setMode("delete")}>
            Apagar registro
          </Button>
        </div>
      )}

      {mode === "sell" && (
        <form onSubmit={confirmSale} noValidate className="mt-5 border-t border-hairline pt-4">
          <p className="font-medium">Por quanto você vendeu?</p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Field label="Preço de venda por unidade (US$)">
              <input className={inputClass} inputMode="decimal" value={salePrice} onChange={(e) => setSalePrice(e.target.value)} />
            </Field>
            <Field label="Data da venda">
              <input className={inputClass} type="date" value={saleDate} min={todayIso(p.entry_ts)} max={todayIso()} onChange={(e) => setSaleDate(e.target.value)} />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button type="submit" variant="primary" busy={busy} icon={<Check size={18} aria-hidden />}>{busy ? "Salvando…" : "Confirmar venda"}</Button>
            <Button variant="ghost" icon={<X size={18} aria-hidden />} onClick={() => setMode("view")} disabled={busy}>Voltar</Button>
          </div>
        </form>
      )}

      {mode === "delete" && (
        <div className="mt-5 border-t border-hairline pt-4">
          <p>Apagar este registro? Use só se você registrou errado — para uma venda, use "Já vendi".</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <Button variant="danger" busy={busy} icon={<Trash size={18} aria-hidden />} onClick={() => void run(() => deletePosition(p.position_id))}>
              {busy ? "Apagando…" : "Apagar"}
            </Button>
            <Button variant="ghost" onClick={() => setMode("view")} disabled={busy}>Manter</Button>
          </div>
        </div>
      )}
      {error !== null && <p role="alert" className="mt-3 text-critical">{error}</p>}
    </article>
  );
}

/* ---------- seção completa ---------- */

export function PositionsSection({ positions, closed, coins, onChanged }: {
  readonly positions: readonly Position[];
  readonly closed: readonly ClosedPosition[];
  readonly coins: readonly DailySignal[];
  readonly onChanged: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const saved = async (): Promise<void> => {
    await onChanged();
    setAdding(false);
  };

  return (
    <>
      {adding ? (
        <PurchaseForm coins={coins} onSaved={saved} onCancel={() => setAdding(false)} />
      ) : (
        <div className="flex flex-wrap items-center gap-4">
          <Button variant="primary" icon={<Plus size={18} aria-hidden />} onClick={() => setAdding(true)}>
            Registrar uma compra
          </Button>
          {positions.length === 0 && <p className="text-muted">Você ainda não registrou nenhuma compra.</p>}
        </div>
      )}

      {positions.length > 0 && (
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {positions.map((p) => <PositionCard key={p.position_id} p={p} onChanged={onChanged} />)}
        </div>
      )}

      {closed.length > 0 && (
        <>
          <h3 className="mt-10 font-medium">Vendas que você registrou</h3>
          <div className="mt-3">
            <Table
              caption="Posições já vendidas e o resultado de cada uma"
              columns={[
                { label: "Moeda" }, { label: "Compra" }, { label: "Venda" },
                { label: "Resultado", numeric: true }, { label: "Ganho/perda", numeric: true },
              ]}
            >
              {closed.map((c) => (
                <tr key={c.position_id} className="border-b border-hairline">
                  <td className={cell}><CoinLabel symbol={c.symbol} size={20} /></td>
                  <td className={cell}>{fmt.price(c.entry_price)} <span className="text-muted">em {fmt.day(c.entry_ts)}</span></td>
                  <td className={cell}>{fmt.price(c.exit_price)} <span className="text-muted">em {fmt.day(c.exit_ts)}</span></td>
                  <td className={`${numCell} ${TEXT_TONE[signTone(c.return_pct)]}`}>{fmt.pct(c.return_pct)}</td>
                  <td className={`${numCell} ${TEXT_TONE[signTone(c.pnl_usd)]}`}>{fmt.usd(c.pnl_usd)}</td>
                </tr>
              ))}
            </Table>
          </div>
        </>
      )}
    </>
  );
}
