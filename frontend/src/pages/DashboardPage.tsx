import { Box, Grid } from '@mui/material';
import SpeedIcon from '@mui/icons-material/Speed';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import AssignmentLateIcon from '@mui/icons-material/AssignmentLate';
import PeopleOutlineIcon from '@mui/icons-material/PeopleOutline';

import DashboardWidget from '../features/dashboard/DashboardWidget';
import VelocityChart from '../features/dashboard/VelocityChart';

export default function DashboardPage() {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* Top Metrics Row */}
      <Grid container spacing={3}>
        <Grid item xs={12} sm={6} md={3}>
          <DashboardWidget
            title="Current Velocity"
            value="55 pts"
            icon={<SpeedIcon />}
            trend={{ value: 12, isPositive: true }}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <DashboardWidget
            title="Completion Rate"
            value="94.8%"
            icon={<CheckCircleOutlineIcon />}
            trend={{ value: 2.4, isPositive: true }}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <DashboardWidget
            title="Scope Creep"
            value="8.2%"
            icon={<AssignmentLateIcon />}
            trend={{ value: 1.1, isPositive: false }} // Negative because more scope creep is bad
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <DashboardWidget
            title="Overloaded Employees"
            value="2"
            icon={<PeopleOutlineIcon />}
            subtitle="Requires workload rebalancing"
          />
        </Grid>
      </Grid>

      {/* Charts Row */}
      <Grid container spacing={3}>
        <Grid item xs={12} lg={8}>
          <VelocityChart />
        </Grid>
        <Grid item xs={12} lg={4}>
          {/* Placeholder for Workload Distribution Pie Chart */}
          <Box sx={{ height: 400, backgroundColor: 'white', borderRadius: 2, border: '1px solid #e2e8f0', p: 3, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'text.secondary' }}>
            Workload Distribution Chart (Coming Soon)
          </Box>
        </Grid>
      </Grid>
    </Box>
  );
}
