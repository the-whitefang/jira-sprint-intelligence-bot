import { Routes, Route } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import DashboardPage from './pages/DashboardPage';
// Placeholders for other pages
import SprintOverviewPage from './pages/SprintOverviewPage';
import EmployeeAnalyticsPage from './pages/EmployeeAnalyticsPage';
import BacklogPage from './pages/BacklogPage';
import ReportsPage from './pages/ReportsPage';
import ChatPage from './pages/ChatPage';
import AdminPage from './pages/AdminPage';
import SettingsPage from './pages/SettingsPage';

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        {/* Main Dashboard */}
        <Route index element={<DashboardPage />} />
        
        {/* Sprint Analytics */}
        <Route path="sprints" element={<SprintOverviewPage />} />
        <Route path="employees" element={<EmployeeAnalyticsPage />} />
        <Route path="backlog" element={<BacklogPage />} />
        
        {/* AI & Reporting */}
        <Route path="chat" element={<ChatPage />} />
        <Route path="reports" element={<ReportsPage />} />
        
        {/* System */}
        <Route path="admin" element={<AdminPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}

export default AppRoutes;
