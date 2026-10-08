import { useEffect, useState } from "react";

function formatMoney(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/invoices")
      .then((response) => response.json())
      .then(setInvoices)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <p role="alert">Could not load invoices: {error}</p>;

  return (
    <main>
      <h1>Invoices</h1>
      <table>
        <thead>
          <tr>
            <th>Invoice</th>
            <th>Order</th>
            <th>Amount</th>
            <th>Paid</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((invoice) => (
            <tr key={invoice.id}>
              <td>{invoice.id}</td>
              <td>{invoice.order_id}</td>
              <td>{formatMoney(invoice.amount_cents)}</td>
              <td>{invoice.paid_at ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
