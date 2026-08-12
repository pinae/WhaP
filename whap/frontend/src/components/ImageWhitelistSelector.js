import React, {useState, useMemo} from 'react';
import {
    Box,
    Select,
    MenuItem,
    FormControl,
    InputLabel,
    Button,
    Chip,
    Stack,
    Typography,
    Paper
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';

function ImageWhitelistSelector({allImages = [], selectedImages = [], onSelectionChange, disabled = false}) {
    const [imageToAdd, setImageToAdd] = useState('');

    // Determine which images are available to be added (not already in the whitelist)
    const availableOptions = useMemo(() => {
        const selectedSet = new Set(selectedImages);
        return allImages.filter(image => !selectedSet.has(image.id));
    }, [allImages, selectedImages]);

    const handleAdd = () => {
        if (imageToAdd && !selectedImages.includes(imageToAdd)) {
            const newSelection = [...selectedImages, imageToAdd].sort();
            onSelectionChange(newSelection);
            setImageToAdd(''); // Reset dropdown
        }
    };

    const handleDelete = (imageToRemove) => {
        const newSelection = selectedImages.filter(image => image !== imageToRemove);
        onSelectionChange(newSelection);
    };

    // Find the display name for a given image ID (role name)
    const getImageName = (imageId) => {
        const image = allImages.find(i => i.id === imageId);
        return image ? image.name : imageId;
    };

    return (
        <Box>
            <Typography variant="subtitle2" sx={{mt: 2, mb: 1}}>Image Whitelist:</Typography>
            <Paper variant="outlined" sx={{p: 1, minHeight: '50px', mb: 1}}>
                {selectedImages.length > 0 ? (
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                        {selectedImages.map(image => (
                            <Chip
                                key={image}
                                label={getImageName(image)}
                                onDelete={() => handleDelete(image)}
                                disabled={disabled}
                            />
                        ))}
                    </Stack>
                ) : (
                    <Typography variant="body2" color="text.secondary" sx={{textAlign: 'center', p: 1}}>
                        No images whitelisted. All images are denied.
                    </Typography>
                )}
            </Paper>

            <Stack direction="row" spacing={1} alignItems="center">
                <FormControl fullWidth size="small">
                    <InputLabel id="image-whitelist-select-label">Add Image</InputLabel>
                    <Select
                        labelId="image-whitelist-select-label"
                        value={imageToAdd}
                        label="Add Image"
                        onChange={(e) => setImageToAdd(e.target.value)}
                        disabled={disabled || availableOptions.length === 0}
                    >
                        <MenuItem value="">
                            <em>{availableOptions.length === 0 ? 'All images added' : 'Select an image'}</em>
                        </MenuItem>
                        {availableOptions.map(image => (
                            <MenuItem key={image.id} value={image.id}>{image.name}</MenuItem>
                        ))}
                    </Select>
                </FormControl>
                <Button
                    variant="outlined"
                    onClick={handleAdd}
                    disabled={disabled || !imageToAdd}
                    startIcon={<AddIcon/>}
                >
                    Add
                </Button>
            </Stack>
        </Box>
    );
}

export default ImageWhitelistSelector;