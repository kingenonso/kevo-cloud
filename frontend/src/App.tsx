import { Routes, Route } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { PlaceholderPage } from "@/pages/Placeholder"
import { LoginPage } from "@/pages/Login"
import { DashboardPage } from "@/pages/Dashboard"
import { WalletPage } from "@/pages/Wallet"
import { ConfirmWithdrawalPage } from "@/pages/ConfirmWithdrawal"
import { MyListingsPage } from "@/pages/MyListings"
import { TransactionsPage } from "@/pages/Transactions"
import { DealRoomPage } from "@/pages/DealRoom"
import { RequireAuth } from "@/components/auth/RequireAuth"

function Page({ title }: { title: string }) {
  return (
    <AppShell title={title}>
      <PlaceholderPage title={title} />
    </AppShell>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<AppShell title="Dashboard"><DashboardPage /></AppShell>} />
        <Route path="/wallet" element={<AppShell title="Wallet"><WalletPage /></AppShell>} />
        <Route path="/confirm-withdrawal" element={<ConfirmWithdrawalPage />} />
        <Route path="/listings" element={<AppShell title="My Listings"><MyListingsPage /></AppShell>} />
        <Route path="/transactions" element={<AppShell title="Transactions"><TransactionsPage /></AppShell>} />
        <Route path="/deal-room" element={<Page title="Deal Room" />} />
        <Route path="/deal-room/:transactionId" element={<AppShell title="Deal Room"><DealRoomPage /></AppShell>} />
        <Route path="/lending" element={<Page title="Lending" />} />
        <Route path="/fx-settlement" element={<Page title="FX Settlement" />} />
        <Route path="/option-funding" element={<Page title="Option Funding" />} />
        <Route path="/tender-offers" element={<Page title="Tender Offers" />} />
        <Route path="/compliance-ledger" element={<Page title="Compliance Ledger" />} />
        <Route path="/kyc" element={<Page title="KYC & AML" />} />
        <Route path="/rofr" element={<Page title="ROFR" />} />
        <Route path="/admin/withdrawal-review" element={<Page title="Withdrawal Review" />} />
        <Route path="/deal-alerts" element={<Page title="Deal Alerts" />} />
        <Route path="/risk-radar" element={<Page title="Risk Radar" />} />
        <Route path="/liquidity-roadmap" element={<Page title="Liquidity Roadmap" />} />
        <Route path="/settings" element={<Page title="Settings" />} />
      </Route>
    </Routes>
  )
}
