import React, {useState, useEffect} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
    Box,
    List,
    ListItemButton,
    ListItemText,
    Typography,
    CircularProgress,
    Alert,
    Divider,
    Drawer,
    Toolbar
} from '@mui/material';
import api from '../services/api';
import Header from '../components/Header';

// Width of the sidebar
const DRAWER_WIDTH = 280;

function DocumentationPage() {
    const [topics, setTopics] = useState([]);
    const [selectedTopicId, setSelectedTopicId] = useState(null);
    const [content, setContent] = useState('');
    const [loadingList, setLoadingList] = useState(true);
    const [loadingContent, setLoadingContent] = useState(false);
    const [error, setError] = useState('');
    const [mobileOpen, setMobileOpen] = useState(false);

    // Fetch the list of topics on mount
    useEffect(() => {
        const fetchTopics = async () => {
            try {
                const response = await api.get('/api/docs/list');
                setTopics(response.data);
                if (response.data.length > 0) {
                    setSelectedTopicId(response.data[0].id); // Select first by default
                }
            } catch (err) {
                console.error("Failed to load documentation list", err);
                setError("Failed to load documentation topics.");
            } finally {
                setLoadingList(false);
            }
        };
        fetchTopics();
    }, []);

    // Fetch content when selection changes
    useEffect(() => {
        if (!selectedTopicId) return;

        const fetchContent = async () => {
            setLoadingContent(true);
            try {
                const response = await api.get(`/api/docs/content/${selectedTopicId}`);
                setContent(response.data);
            } catch (err) {
                console.error("Failed to load topic content", err);
                setContent("# Error\nCould not load this topic.");
            } finally {
                setLoadingContent(false);
            }
        };
        fetchContent();

        // On mobile, close drawer after selection
        setMobileOpen(false);
    }, [selectedTopicId]);

    const handleDrawerToggle = () => {
        setMobileOpen(!mobileOpen);
    };

    // Custom image renderer to redirect image paths to our API
    const MarkdownComponents = {
        img: ({node, ...props}) => {
            // Check if it's a relative path (not starting with http)
            let src = props.src;
            if (src && !src.startsWith('http')) {
                // Remove leading slash if present
                const cleanSrc = src.startsWith('/') ? src.slice(1) : src;
                // Redirect to our API endpoint
                src = `${api.defaults.baseURL}/api/docs/images/${cleanSrc}`;
            }
            return <img {...props} src={src} style={{maxWidth: '100%', height: 'auto'}} alt={props.alt}/>;
        }
    };

    // The content inside the sidebar
    const drawerContent = (
        <Box sx={{height: '100%', display: 'flex', flexDirection: 'column'}}>
            <Toolbar>
                <Typography variant="h6" noWrap component="div" sx={{color: 'text.secondary'}}>
                    Documentation
                </Typography>
            </Toolbar>
            <Divider/>
            {loadingList ? (
                <Box sx={{p: 2, textAlign: 'center'}}><CircularProgress size={20}/></Box>
            ) : (
                <List component="nav" sx={{flexGrow: 1, overflowY: 'auto'}}>
                    {topics.map((topic) => (
                        <ListItemButton
                            key={topic.id}
                            selected={selectedTopicId === topic.id}
                            onClick={() => setSelectedTopicId(topic.id)}
                            sx={{
                                '&.Mui-selected': {
                                    borderRight: '4px solid',
                                    borderColor: 'primary.main',
                                    backgroundColor: 'action.selected'
                                }
                            }}
                        >
                            <ListItemText primary={topic.title}/>
                        </ListItemButton>
                    ))}
                    {topics.length === 0 && <Typography sx={{p: 2}}>No documentation found.</Typography>}
                </List>
            )}
        </Box>
    );

    return (
        <Box sx={{display: 'flex', minHeight: '100vh', backgroundColor: '#ffffff'}}>

            {/* 1. Mobile Drawer (Temporary) */}
            <Drawer
                variant="temporary"
                open={mobileOpen}
                onClose={handleDrawerToggle}
                ModalProps={{keepMounted: true}} // Better open performance on mobile.
                sx={{
                    display: {xs: 'block', md: 'none'}, // Only show on small screens
                    '& .MuiDrawer-paper': {boxSizing: 'border-box', width: DRAWER_WIDTH},
                }}
            >
                {drawerContent}
            </Drawer>

            {/* 2. Desktop Drawer (Permanent) */}
            <Drawer
                variant="permanent"
                sx={{
                    display: {xs: 'none', md: 'block'}, // Hide on small screens, show on medium (900px+)
                    '& .MuiDrawer-paper': {
                        boxSizing: 'border-box',
                        width: DRAWER_WIDTH,
                        borderRight: '1px solid #e0e0e0'
                    },
                }}
                open
            >
                {drawerContent}
            </Drawer>

            {/* 3. Main Content Area */}
            <Box
                component="main"
                sx={{
                    flexGrow: 1,
                    p: 3,
                    width: {md: `calc(100% - ${DRAWER_WIDTH}px)`}, // Adjust width on desktop
                    maxWidth: '100vw', // Prevent overflow
                }}
            >
                {/* Header is now part of the main content area, shifting right with the content */}
                <Header title="Documentation" onMenuClick={handleDrawerToggle}/>

                {error && <Alert severity="error" sx={{mb: 2}}>{error}</Alert>}

                {/* Markdown Container with "80 characters" readability constraint */}
                <Box sx={{maxWidth: '85ch', margin: '0 auto'}}>
                    {loadingContent ? (
                        <Box sx={{display: 'flex', justifyContent: 'center', mt: 4}}>
                            <CircularProgress/>
                        </Box>
                    ) : (
                        <Box className="markdown-body">
                            <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={MarkdownComponents}
                            >
                                {content}
                            </ReactMarkdown>
                        </Box>
                    )}
                </Box>
            </Box>
        </Box>
    );
}

export default DocumentationPage;