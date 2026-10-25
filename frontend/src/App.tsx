import { Routes, Route } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { LoginPage } from "@/pages/Login"
import { DashboardPage } from "@/pages/Dashboard"
import { WalletPage } from "@/pages/Wallet"
import { ConfirmWithdrawalPage } from "@/pages/ConfirmWithdrawal"
import { MyListingsPage } from "@/pages/MyListings"
import { TransactionsPage } from "@/pages/Transactions"
import { DealRoomPage } from "@/pages/DealRoom"
import { DealRoomIndexPage } from "@/pages/DealRoomIndex"
import { RequireAuth } from "@/components/auth/RequireAuth"
import { LendingPage } from "@/pages/Lending"
import { FxSettlementPage } from "@/pages/FxSettlement"
import { OptionFundingPage } from "@/pages/OptionFunding"
import { TenderOffersPage } from "@/pages/TenderOffers"
import { ComplianceLedgerPage } from "@/pages/ComplianceLedger"
import { KycPage } from "@/pages/Kyc"
import { RofrPage } from "@/pages/Rofr"
import { WithdrawalReviewPage } from "@/pages/WithdrawalReview"
import { DealAlertsPage } from "@/pages/DealAlerts"
import { RiskRadarPage } from "@/pages/RiskRadar"
import { LiquidityRoadmapPage } from "@/pages/LiquidityRoadmap"
import { SettingsPage } from "@/pages/Settings"
import { EligibilityPage } from "@/pages/Eligibility"
import { EvidencePage } from "@/pages/Evidence"
import { MarketIntelligencePage } from "@/pages/MarketIntelligence"
import { LiquidityEventRadarPage } from "@/pages/LiquidityEventRadar"
import { SpeedDiscountPage } from "@/pages/SpeedDiscount"
import { SpvPoolsPage } from "@/pages/SpvPools"
import { ForwardSaleContractsPage } from "@/pages/ForwardSaleContracts"
import { SellerFinancingPage } from "@/pages/SellerFinancing"
import { SettlementPage } from "@/pages/Settlement"
import { BrowsePage } from "@/pages/Browse"
import { CostCalculatorPage } from "@/pages/CostCalculator"
import { IssuerPortalPage } from "@/pages/IssuerPortal"
import { PlatformAccessPage } from "@/pages/PlatformAccess"
import { InsightsDashboardPage } from "@/pages/InsightsDashboard"
import { RuleChangeAlertsPage } from "@/pages/RuleChangeAlerts"
import { AuditLogPage } from "@/pages/AuditLog"

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
        <Route path="/deal-room" element={<AppShell title="Deal Room"><DealRoomIndexPage /></AppShell>} />
        <Route path="/deal-room/:transactionId" element={<AppShell title="Deal Room"><DealRoomPage /></AppShell>} />
        <Route path="/lending" element={<AppShell title="Lending"><LendingPage /></AppShell>} />
        <Route path="/fx-settlement" element={<AppShell title="FX Settlement"><FxSettlementPage /></AppShell>} />
        <Route path="/option-funding" element={<AppShell title="Option Funding"><OptionFundingPage /></AppShell>} />
        <Route path="/tender-offers" element={<AppShell title="Tender Offers"><TenderOffersPage /></AppShell>} />
        <Route path="/spv-pools" element={<AppShell title="SPV Pools"><SpvPoolsPage /></AppShell>} />
        <Route path="/forward-sale-contracts" element={<AppShell title="Forward Sale Contracts"><ForwardSaleContractsPage /></AppShell>} />
        <Route path="/seller-financing" element={<AppShell title="Seller Financing"><SellerFinancingPage /></AppShell>} />
        <Route path="/settlement" element={<AppShell title="Settlement"><SettlementPage /></AppShell>} />
        <Route path="/compliance-ledger" element={<AppShell title="Compliance Ledger"><ComplianceLedgerPage /></AppShell>} />
        <Route path="/kyc" element={<AppShell title="KYC & AML"><KycPage /></AppShell>} />
        <Route path="/rofr" element={<AppShell title="ROFR"><RofrPage /></AppShell>} />
        <Route path="/eligibility" element={<AppShell title="Eligibility"><EligibilityPage /></AppShell>} />
        <Route path="/admin/withdrawal-review" element={<AppShell title="Withdrawal Review"><WithdrawalReviewPage /></AppShell>} />
        <Route path="/deal-alerts" element={<AppShell title="Deal Alerts"><DealAlertsPage /></AppShell>} />
        <Route path="/risk-radar" element={<AppShell title="Risk Radar"><RiskRadarPage /></AppShell>} />
        <Route path="/liquidity-roadmap" element={<AppShell title="Liquidity Roadmap"><LiquidityRoadmapPage /></AppShell>} />
        <Route path="/market-intelligence" element={<AppShell title="Market Intelligence"><MarketIntelligencePage /></AppShell>} />
        <Route path="/liquidity-event-radar" element={<AppShell title="Liquidity Event Radar"><LiquidityEventRadarPage /></AppShell>} />
        <Route path="/speed-discount" element={<AppShell title="Speed Discount"><SpeedDiscountPage /></AppShell>} />
        <Route path="/browse" element={<AppShell title="Browse"><BrowsePage /></AppShell>} />
        <Route path="/evidence" element={<AppShell title="Evidence"><EvidencePage /></AppShell>} />
        <Route path="/cost-calculator" element={<AppShell title="Cost Calculator"><CostCalculatorPage /></AppShell>} />
        <Route path="/settings" element={<AppShell title="Settings"><SettingsPage /></AppShell>} />
        <Route path="/issuer-portal" element={<AppShell title="Issuer Portal"><IssuerPortalPage /></AppShell>} />
        <Route path="/admin/platform-access" element={<AppShell title="Platform Access"><PlatformAccessPage /></AppShell>} />
        <Route path="/insights-dashboard" element={<AppShell title="Insights Dashboard"><InsightsDashboardPage /></AppShell>} />
        <Route path="/rule-change-alerts" element={<AppShell title="Rule-Change Alerts"><RuleChangeAlertsPage /></AppShell>} />
        <Route path="/admin/audit-log" element={<AppShell title="Audit Log"><AuditLogPage /></AppShell>} />
      </Route>
    </Routes>
  )
}
