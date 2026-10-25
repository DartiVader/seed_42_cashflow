import { Navigate, Route, Routes } from "react-router";
import Header from "@/layouts/Header";
import ThemeToggle from "@/components/ThemeToggle";
import ProtectedRoute from "@/routes/ProtectedRoute";
import LandingPage from "@/pages/LandingPage";
import AuthPage from "@/pages/AuthPage";
import DashboardPage from "@/pages/DashboardPage";
import ForecastPage from "@/pages/ForecastPage";
import QualityPage from "@/pages/QualityPage";

const App = () => {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/demo" element={<ForecastPage demoOnly />} />
        <Route path="/demo/:companyId" element={<ForecastPage demoOnly />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/forecast" element={<ForecastPage />} />
          <Route path="/forecast/:companyId" element={<ForecastPage />} />
          <Route path="/quality" element={<QualityPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ThemeToggle />
    </>
  )
}

export default App
