import { Check, CurrencyDollar, Plus, Receipt, ShieldWarning, Tag, Trash, TrendDown, X } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError, addPurchase, deletePosition, registerSale } from "../data/api";
import { REASON_TEXT, coinName, fmt, parseAmount, signTone, toInput, todayIso } from "../data/analytics";
import type { ClosedPosition, DailySignal, Position } from "../types/signals";
import { CoinLabel } from "./CoinLabel";
import { REASON_ICON } from "./icons";
import { Badge, Button, Field, TEXT_TONE, Table, cell, inputClass, numCell } from "./ui";

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
    <div>
      <form onSubmit={(e) => void submit(e)} noValidate>
        <h3 className="flex items-center gap-2 text-[14px] font-semibold"><Receipt size={18} aria-hidden /> Registrar uma compra</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <Field label="Qual moeda você comprou?">
            <select className={inputClass} value={symbol} onChange={(e) => pick(e.target.value)}>
              {coins.map((c) => <option key={c.symbol} value={c.symbol}>{coinName(c.symbol)}</option>)}
            </select>
          </Field>
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

        <p className="mt-3 text-muted">
          Total investido: <strong className="num font-medium text-ink">{fmt.usd(total)}</strong>
        </p>
        {error !== null && <p role="alert" className="mt-3 text-critical">{error}</p>}

        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="submit" variant="primary" busy={busy} icon={<Check size={18} aria-hidden />}>
            {busy ? "Salvando…" : `Registrar compra de ${coinName(symbol)}`}
          </Button>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancelar</Button>
        </div>
      </form>
    </div>
  );
}

/* ---------- ficha de uma posição ---------- */

function Fact({ icon, label, value }: { readonly icon: ReactNode; readonly label: string; readonly value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-hairline py-1 text-[12px]">
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
    <article className="rounded-md border border-hairline bg-surface p-3" aria-label={`Posição em ${coinName(p.symbol)}`}>
      <div className="flex items-start justify-between gap-4">
        <CoinLabel symbol={p.symbol} detailed size={28} />
        {sell ? <Badge tone="critical">Vender</Badge> : p.action === "INDISPONÍVEL" ? <Badge tone="warning">Sem dados</Badge> : <Badge tone="good">Segurar</Badge>}
      </div>
      <p className="mt-1 text-[12px] text-muted">{fmt.num(p.qty, 4)} unidades compradas em {fmt.day(p.entry_ts)}</p>

      <p className={`num mt-2 text-[20px] font-medium leading-tight ${TEXT_TONE[signTone(p.return_pct)]}`}>
        {fmt.pct(p.return_pct)} <span className="text-[14px]">{fmt.usd(p.pnl_usd)}</span>
      </p>
      <p className="mt-1 flex gap-2 text-[12px] text-muted">
        {ReasonIcon !== null && <ReasonIcon size={20} className="mt-0.5 shrink-0 text-critical" aria-hidden />}
        <span>
          {p.action === "INDISPONÍVEL"
            ? `Sem dados confiáveis hoje: ${p.data_note ?? "motivo desconhecido"}. Não dá para recomendar vender nem segurar.`
            : sell && p.reason !== null
            ? `${REASON_TEXT[p.reason].replace(/^./, (c) => c.toUpperCase())} (desde ${fmt.day(p.signal_ts)}).`
            : "Nenhuma regra de venda disparou. A moeda segue em tendência de alta: pode continuar com ela."}
        </span>
      </p>

      <dl className="mt-2">
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
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant={sell ? "primary" : "secondary"} icon={<Check size={18} aria-hidden />} onClick={() => setMode("sell")}>
            Já vendi
          </Button>
          <Button variant="ghost" icon={<Trash size={18} aria-hidden />} onClick={() => setMode("delete")}>
            Apagar registro
          </Button>
        </div>
      )}

      {mode === "sell" && (
        <form onSubmit={confirmSale} noValidate className="mt-3 border-t border-hairline pt-3">
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
        <div className="mt-3 border-t border-hairline pt-3">
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
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" icon={<Plus size={18} aria-hidden />} onClick={() => setAdding(true)}>
            Registrar uma compra
          </Button>
          {positions.length === 0 && <p className="text-muted">Você ainda não registrou nenhuma compra.</p>}
        </div>
      )}

      {positions.length > 0 && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {positions.map((p) => <PositionCard key={p.position_id} p={p} onChanged={onChanged} />)}
        </div>
      )}

      {closed.length > 0 && (
        <>
          <h3 className="mt-4 text-[13px] font-medium">Vendas que você registrou</h3>
          <div className="mt-2">
            <Table
              maxHeight="max-h-48"
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
