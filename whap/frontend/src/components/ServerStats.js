import React, {useState, useEffect, useMemo} from 'react';
import {
    Box,
    Paper,
    Typography,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Chip,
    CircularProgress,
    Grid,
    Tooltip as MuiTooltip,
} from '@mui/material';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip as ChartTooltip,
    Legend,
    Filler
} from 'chart.js';
import {Line} from 'react-chartjs-2';
import api from '../services/api';

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    ChartTooltip,
    Legend,
    Filler
);

// Colors for GPUs to keep them consistent across graphs
const GPU_COLORS = [
    'rgb(255, 99, 132)',   // Red
    'rgb(54, 162, 235)',   // Blue
    'rgb(255, 206, 86)',   // Yellow
    'rgb(75, 192, 192)',   // Teal
    'rgb(153, 102, 255)',  // Purple
    'rgb(255, 159, 64)'    // Orange
];

function ServerStats({server}) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                // Fetch 3 hours of data to show a nice history
                const res = await api.get(`/api/stats/${server.hostname.split('.')[0]}`);
                setData(res.data);
            } catch (err) {
                console.error(`Failed to fetch stats for ${server.hostname}`, err);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
        const interval = setInterval(fetchData, 60000); // Refresh every minute
        return () => clearInterval(interval);
    }, [server.hostname]);

    // --- Prepare Chart Data ---
    const charts = useMemo(() => {
        if (!data) return null;

        const labels = (data.timestamps || []).map(t => {
            const d = new Date(t);
            return `${d.getHours()}:${d.getMinutes().toString().padStart(2, '0')}`;
        });

        // 1. GPU & VRAM Stacked Chart Data
        const gpuDatasets = [];

        if (data.gpus) {
            // GPU Utilization Lines
            Object.keys(data.gpus).forEach((idx, i) => {
                const color = GPU_COLORS[i % GPU_COLORS.length];
                gpuDatasets.push({
                    label: `GPU ${idx} Util (%)`,
                    data: data.gpus[idx].util || [],
                    borderColor: color,
                    backgroundColor: color,
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.4,
                    yAxisID: 'y_util',
                });
            });

            // VRAM Usage Lines
            Object.keys(data.gpus).forEach((idx, i) => {
                const color = GPU_COLORS[i % GPU_COLORS.length];
                gpuDatasets.push({
                    label: `GPU ${idx} VRAM (MB)`,
                    data: data.gpus[idx].mem || [],
                    borderColor: color,
                    backgroundColor: color,
                    borderWidth: 1,
                    borderDash: [5, 5],
                    pointRadius: 0,
                    tension: 0.4,
                    yAxisID: 'y_mem',
                    hidden: false,
                });
            });
        }

        // 2. System Load (CPU/RAM) Chart Data
        const sysDatasets = [
            {
                label: 'CPU Load (%)',
                data: data.cpu || [],
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                yAxisID: 'y_cpu',
            },
            {
                label: 'RAM Usage (MB)',
                data: data.ram || [],
                borderColor: 'rgb(153, 102, 255)',
                backgroundColor: 'transparent',
                borderDash: [5, 5],
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0,
                yAxisID: 'y_ram',
            }
        ];

        return {labels, gpuDatasets, sysDatasets};
    }, [data]);

    const serverStatus = useMemo(() => {
        if (!data || !data.timestamps || data.timestamps.length === 0) {
            return { label: 'Offline', color: 'error' };
        }

        const lastTimestampStr = data.timestamps[data.timestamps.length - 1];
        const lastTimestamp = new Date(lastTimestampStr).getTime();
        const now = Date.now();
        // Calculate difference in seconds
        const diffSeconds = (now - lastTimestamp) / 1000;

        // Status is Online if data is fresher than 120 seconds
        if (diffSeconds <= 120) {
            return { label: 'Online', color: 'success' };
        } else {
            return { label: 'Offline', color: 'error' };
        }
    }, [data]);

    if (loading) return <CircularProgress sx={{display: 'block', mx: 'auto', my: 4}}/>;
    if (!data) return <Typography sx={{p: 2}}>No data available for {server.hostname}</Typography>;

    // --- Chart Options ---
    let mem_max = 0.0;
    Object.keys(data.gpus).forEach((idx, i) => {
        mem_max = Math.max(mem_max, data.gpus[idx].mem_total)
    })
    const gpuChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {mode: 'index', intersect: false},
        stacked: true,
        plugins: {
            title: {display: true, text: 'GPU Utilization'},
            tooltip: {
                callbacks: {
                    label: (context) => {
                        let label = context.dataset.label || '';
                        if (label) label += ': ';
                        if (context.parsed.y !== null) label += Math.round(context.parsed.y);
                        return label;
                    }
                }
            }
        },
        scales: {
            x: {ticks: {maxTicksLimit: 12}},
            y_util: {
                type: 'linear',
                display: true,
                position: 'left',
                title: {display: true, text: 'Utilization %'},
                max: 100,
                min: 0,
                stack: 'gpudata',
                stackWeight: 1,
            },
            y_mem: {
                type: 'linear',
                display: true,
                position: 'left',
                title: {display: true, text: 'VRAM (MB)'},
                offset: true,
                min: 0,
                max: mem_max,
                stack: 'gpudata',
                stackWeight: 1,
                grid: {drawOnChartArea: false},
            },
            y_mem_right: {
                type: 'linear',
                display: true,
                position: 'right',
                title: {display: true, text: 'VRAM (MB)'},
                offset: true,
                min: 0,
                max: mem_max,
                stack: 'gpudata_right',
                stackWeight: 1,
                grid: {drawOnChartArea: false},
            },
            y_util_right: {
                type: 'linear',
                display: true,
                position: 'right',
                title: {display: true, text: 'Utilization %'},
                max: 100,
                min: 0,
                stack: 'gpudata_right',
                stackWeight: 1,
            },
        },
    };

    const sysChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {mode: 'index', intersect: false},
        plugins: {
            title: {display: true, text: 'System Load (CPU & RAM)'},
        },
        scales: {
            x: {ticks: {maxTicksLimit: 12}},
            y_cpu: {
                type: 'linear',
                display: true,
                position: 'left',
                title: {display: true, text: 'CPU %'},
                max: 100,
                min: 0,
            },
            y_ram: {
                type: 'linear',
                display: true,
                position: 'right',
                title: {display: true, text: 'RAM (MB)'},
                grid: {drawOnChartArea: false},
                suggestedMax: data.ram_total || 16000,
            },
        },
    };

    // Check if Line component is valid before rendering
    if (!Line) {
        return <Typography color="error">Error: Chart component failed to load.</Typography>;
    }

    return (
        <Paper elevation={3} sx={{p: 3, mb: 4, borderLeft: '6px solid #1976d2'}}>
            <Box sx={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2}}>
                <Typography variant="h5" component="div" sx={{fontWeight: 'bold'}}>
                    {server.hostname}
                </Typography>
                <Chip
                    label={serverStatus.label}
                    color={serverStatus.color}
                    size="small"
                    variant="outlined"
                />
            </Box>

            <div container spacing={4}>
                {/* GPU Chart */}
                <Grid item xs={12} lg={6}>
                    <Box sx={{height: 300}}>
                        {charts && <Line data={{labels: charts.labels, datasets: charts.gpuDatasets}}
                                         options={gpuChartOptions}/>}
                    </Box>
                </Grid>

                {/* System Chart */}
                <Grid item xs={12} lg={6}>
                    <Box sx={{height: 200}}>
                        {charts && <Line data={{labels: charts.labels, datasets: charts.sysDatasets}}
                                         options={sysChartOptions}/>}
                    </Box>
                </Grid>

                {/* Process Table */}
                <div>
                    <Typography variant="subtitle1" gutterBottom sx={{fontWeight: 'bold', mt: 1}}>
                        Active Workloads ({'>'}5% Usage)
                    </Typography>
                    <TableContainer component={Paper} variant="outlined" sx={{maxHeight: 300}}>
                        <Table size="small" stickyHeader>
                            <TableHead>
                                <TableRow>
                                    <TableCell sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        User
                                    </TableCell>
                                    <TableCell sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        Command
                                    </TableCell>
                                    <TableCell sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        PID
                                    </TableCell>
                                    <TableCell align="center" sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        GPU #
                                    </TableCell>
                                    <TableCell align="right" sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        GPU %
                                    </TableCell>
                                    <TableCell align="right" sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        VRAM %
                                    </TableCell>
                                    <TableCell align="right" sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        CPU %
                                    </TableCell>
                                    <TableCell align="right" sx={{fontWeight: 'bold', backgroundColor: '#f5f5f5'}}>
                                        MEM %
                                    </TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {data.processes && data.processes.length > 0 ? (
                                    data.processes.map((proc) => (
                                        <TableRow key={proc.pid} hover>
                                            <TableCell>{proc.user}</TableCell>
                                            <TableCell sx={{
                                                fontFamily: 'monospace',
                                                fontSize: '0.85rem',
                                                maxWidth: 300,
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap'
                                            }}>
                                                <MuiTooltip title={proc.cmd}>
                                                    <span>{proc.cmd}</span>
                                                </MuiTooltip>
                                            </TableCell>
                                            <TableCell>{proc.pid}</TableCell>
                                            <TableCell align="center">
                                                {proc.gpu_idx !== undefined ? (
                                                    <Chip label={proc.gpu_idx} size="small"
                                                          sx={{height: 20, minWidth: 20}} />
                                                ) : "-"}
                                            </TableCell>
                                            <TableCell align="right">
                                                {proc.gpu_util !== undefined ? (
                                                    <Chip
                                                        label={proc.gpu_util}
                                                        size="small"
                                                        variant="outlined"
                                                        color={proc.gpu_util > 80 ? "error" : "primary"}
                                                        sx={{minWidth: 50, height: 20, border: 'none'}}
                                                    />
                                                ) : "-"}
                                            </TableCell>
                                            <TableCell align="right">
                                                {proc.gpu_mem_pct !== undefined ? proc.gpu_mem_pct : "-"}
                                            </TableCell>
                                            <TableCell align="right">
                                                <Chip label={proc.cpu} size="small"
                                                      color={proc.cpu > 80 ? "error" : "default"} variant="filled"
                                                      sx={{minWidth: 50}}/>
                                            </TableCell>
                                            <TableCell align="right">{proc.mem}</TableCell>
                                        </TableRow>
                                    ))
                                ) : (
                                    <TableRow>
                                        <TableCell colSpan={5} align="center" sx={{color: 'text.secondary', py: 3}}>
                                            System is idle. No heavy processes detected.
                                        </TableCell>
                                    </TableRow>
                                )}
                            </TableBody>
                        </Table>
                    </TableContainer>
                </div>
            </div>
        </Paper>
    );
}

export default ServerStats;