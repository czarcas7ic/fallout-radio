/**
 * Fallout Radio - Frontend JavaScript
 * Handles SocketIO connection, UI updates, and user interactions
 */

// =============================================================================
// Global State & Socket Connection
// =============================================================================

let socket = null;
let currentState = {
    pack: null,
    station: null,
    station_index: 0,
    volume: 50,
    status: 'stopped',
    is_on: false,
    initializing: true,
    init_progress: null
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    initPage();
});

// =============================================================================
// Socket.IO Connection
// =============================================================================

function initSocket() {
    socket = io();

    socket.on('connect', () => {
        console.log('Connected to server');
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from server');
    });

    socket.on('state_update', (state) => {
        console.log('State update:', state);
        currentState = state;
        updateUI();
    });
}

// =============================================================================
// Page Detection & Initialization
// =============================================================================

function initPage() {
    const path = window.location.pathname;

    if (path === '/' || path === '') {
        initNowPlayingPage();
    } else if (path === '/packs') {
        initPacksPage();
    } else if (path.startsWith('/packs/')) {
        initPackEditorPage();
    } else if (path === '/settings') {
        initSettingsPage();
    }
}

// =============================================================================
// Now Playing Page
// =============================================================================

function initNowPlayingPage() {
    // Volume slider
    const volumeSlider = document.getElementById('volume');
    const volumeValue = document.getElementById('volume-value');

    if (volumeSlider) {
        volumeSlider.addEventListener('input', (e) => {
            const level = parseInt(e.target.value);
            volumeValue.textContent = level;
        });

        volumeSlider.addEventListener('change', (e) => {
            const level = parseInt(e.target.value);
            socket.emit('set_volume', { level });
        });
    }

    // Control buttons
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const powerBtn = document.getElementById('power-btn');

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            socket.emit('switch_station', { direction: 'prev' });
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            socket.emit('switch_station', { direction: 'next' });
        });
    }

    if (powerBtn) {
        powerBtn.addEventListener('click', () => {
            socket.emit('switch_station', { direction: 'power' });
        });
    }

    // Initial state fetch
    fetchState();
}

function updateUI() {
    // Update initialization overlay
    updateInitOverlay();
    // Update Now Playing page elements if present
    updateNowPlaying();
}

function updateInitOverlay() {
    const overlay = document.getElementById('init-overlay');
    const barFill = document.getElementById('init-bar-fill');
    const status = document.getElementById('init-status');
    const nowPlaying = document.querySelector('.now-playing');

    if (!overlay) return;

    if (currentState.initializing && currentState.init_progress) {
        overlay.classList.remove('hidden');
        if (nowPlaying) nowPlaying.classList.add('disabled');

        const progress = currentState.init_progress;
        const percent = progress.total > 0
            ? Math.round((progress.complete / progress.total) * 100)
            : 0;

        if (barFill) barFill.style.width = percent + '%';
        if (status) {
            if (progress.current_station) {
                status.textContent = `Loading: ${progress.current_station} (${progress.complete}/${progress.total})`;
            } else {
                status.textContent = `${progress.complete}/${progress.total} stations loaded`;
            }
        }
    } else if (!currentState.initializing) {
        overlay.classList.add('hidden');
        if (nowPlaying) nowPlaying.classList.remove('disabled');
    }
}

function updateNowPlaying() {
    const packName = document.getElementById('pack-name');
    const stationName = document.getElementById('station-name');
    const status = document.getElementById('status');
    const volumeSlider = document.getElementById('volume');
    const volumeValue = document.getElementById('volume-value');
    const powerBtn = document.getElementById('power-btn');
    const dialNeedle = document.getElementById('dial-needle');
    const dialMarkers = document.getElementById('dial-markers');

    if (packName && currentState.pack) {
        packName.textContent = currentState.pack.name;
        // Update browser tab title
        document.title = `Now Playing - ${currentState.pack.name}`;
    }

    if (stationName) {
        if (currentState.station) {
            stationName.textContent = currentState.station.name;
        } else {
            stationName.textContent = 'OFF';
        }
    }

    if (status) {
        status.textContent = currentState.status.toUpperCase();
        status.className = 'status ' + currentState.status;
    }

    if (volumeSlider && volumeValue) {
        volumeSlider.value = currentState.volume;
        volumeValue.textContent = currentState.volume;
    }

    // Update power button state (shows action, not current state)
    if (powerBtn) {
        if (currentState.is_on) {
            powerBtn.classList.add('active');
            powerBtn.textContent = 'OFF';
        } else {
            powerBtn.classList.remove('active');
            powerBtn.textContent = 'ON';
        }
    }

    // Update tuner dial
    if (dialNeedle && currentState.pack) {
        updateTunerDial(currentState.station_index, currentState.pack.station_count);
    }
}

function updateTunerDial(currentIndex, stationCount) {
    const dialMarkers = document.getElementById('dial-markers');
    const dialNeedle = document.getElementById('dial-needle');

    if (!dialMarkers || !dialNeedle) return;

    // Clear existing markers
    dialMarkers.innerHTML = '';

    // Create markers for stations only (no OFF position)
    // Stations are 1-indexed (1, 2, 3, ...)
    for (let i = 1; i <= stationCount; i++) {
        const marker = document.createElement('div');
        marker.className = 'dial-marker';
        if (i === currentIndex) marker.classList.add('active');

        // Calculate angle (-70 to 70 degrees, spread across stations)
        const angleRange = 140; // Total angle range
        const startAngle = -70;
        // Position based on station number (1 to stationCount)
        const angle = startAngle + ((i - 1) / Math.max(stationCount - 1, 1)) * angleRange;
        marker.style.transform = `rotate(${angle}deg)`;

        dialMarkers.appendChild(marker);
    }

    // Update needle position
    // If radio is off (index 0), position needle all the way left
    // Otherwise position based on station (1-indexed)
    const angleRange = 140;
    const startAngle = -70;
    let needleAngle;
    if (currentIndex === 0) {
        // Radio is off - needle at leftmost position
        needleAngle = -90;
    } else {
        // Position needle at the station marker
        needleAngle = startAngle + ((currentIndex - 1) / Math.max(stationCount - 1, 1)) * angleRange;
    }
    dialNeedle.style.transform = `rotate(${needleAngle}deg)`;
}

async function fetchState() {
    try {
        const response = await fetch('/api/state');
        currentState = await response.json();
        updateUI();
    } catch (error) {
        console.error('Failed to fetch state:', error);
    }
}

// =============================================================================
// Packs Page
// =============================================================================

let deletePackId = null;

function initPacksPage() {
    loadPacks();

    // Create pack button
    const createBtn = document.getElementById('create-pack-btn');
    const nameInput = document.getElementById('new-pack-name');

    if (createBtn && nameInput) {
        createBtn.addEventListener('click', () => createPack(nameInput));
        nameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') createPack(nameInput);
        });
    }

    // Delete modal
    const cancelDeleteBtn = document.getElementById('cancel-delete-btn');
    const confirmDeleteBtn = document.getElementById('confirm-delete-btn');

    if (cancelDeleteBtn) {
        cancelDeleteBtn.addEventListener('click', closeDeleteModal);
    }

    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', confirmDeletePack);
    }
}

async function loadPacks() {
    const packsList = document.getElementById('packs-list');
    if (!packsList) return;

    try {
        const response = await fetch('/api/packs');
        const data = await response.json();
        renderPacksList(data.packs);
    } catch (error) {
        console.error('Failed to load packs:', error);
        packsList.innerHTML = '<div class="empty-state">Failed to load packs</div>';
    }
}

function renderPacksList(packs) {
    const packsList = document.getElementById('packs-list');
    if (!packsList) return;

    if (packs.length === 0) {
        packsList.innerHTML = '<div class="empty-state">No packs yet. Create one below!</div>';
        return;
    }

    packsList.innerHTML = packs.map(pack => `
        <div class="pack-item ${pack.is_active ? 'active' : ''}" data-pack-id="${pack.id}">
            <div class="active-indicator"></div>
            <div class="pack-name">${escapeHtml(pack.name)}</div>
            <div class="station-count">${pack.stations.length} stations</div>
            <div class="pack-actions">
                <button class="activate-btn" ${pack.is_active ? 'disabled' : ''}>
                    ${pack.is_active ? 'Active' : 'Activate'}
                </button>
                <button class="edit-btn">Edit</button>
                <button class="delete-btn danger">Delete</button>
            </div>
        </div>
    `).join('');

    // Add event listeners
    packsList.querySelectorAll('.pack-item').forEach(item => {
        const packId = item.dataset.packId;

        item.querySelector('.activate-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            activatePack(packId);
        });

        item.querySelector('.edit-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            window.location.href = `/packs/${packId}`;
        });

        item.querySelector('.delete-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            const name = item.querySelector('.pack-name').textContent;
            showDeleteModal(packId, name);
        });
    });
}

async function createPack(nameInput) {
    const name = nameInput.value.trim();
    if (!name) return;

    try {
        const response = await fetch('/api/packs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });

        if (response.ok) {
            nameInput.value = '';
            loadPacks();
        }
    } catch (error) {
        console.error('Failed to create pack:', error);
    }
}

async function activatePack(packId) {
    try {
        await fetch(`/api/packs/${packId}/activate`, { method: 'POST' });
        loadPacks();
    } catch (error) {
        console.error('Failed to activate pack:', error);
    }
}

function showDeleteModal(packId, packName) {
    deletePackId = packId;
    document.getElementById('delete-pack-name').textContent = packName;
    document.getElementById('delete-modal').classList.add('active');
}

function closeDeleteModal() {
    deletePackId = null;
    document.getElementById('delete-modal').classList.remove('active');
}

async function confirmDeletePack() {
    if (!deletePackId) return;

    try {
        await fetch(`/api/packs/${deletePackId}`, { method: 'DELETE' });
        closeDeleteModal();
        loadPacks();
    } catch (error) {
        console.error('Failed to delete pack:', error);
    }
}

// =============================================================================
// Pack Editor Page
// =============================================================================

let currentPackId = null;
let currentPack = null;
let editingStationId = null;
let deleteStationId = null;

function initPackEditorPage() {
    const packEditor = document.querySelector('.pack-editor');
    if (!packEditor) return;

    currentPackId = packEditor.dataset.packId;
    loadPack();

    // Save pack button
    document.getElementById('save-pack-btn')?.addEventListener('click', savePack);

    // Delete pack button
    document.getElementById('delete-pack-btn')?.addEventListener('click', () => {
        if (confirm('Are you sure you want to delete this pack?')) {
            deletePack();
        }
    });

    // Add station button
    document.getElementById('add-station-btn')?.addEventListener('click', addStation);

    // Edit station modal
    document.getElementById('cancel-edit-btn')?.addEventListener('click', closeEditStationModal);
    document.getElementById('save-station-btn')?.addEventListener('click', saveStation);

    // Delete station modal
    document.getElementById('cancel-delete-station-btn')?.addEventListener('click', closeDeleteStationModal);
    document.getElementById('confirm-delete-station-btn')?.addEventListener('click', confirmDeleteStation);
}

async function loadPack() {
    if (!currentPackId) return;

    try {
        const response = await fetch(`/api/packs/${currentPackId}`);
        if (!response.ok) {
            window.location.href = '/packs';
            return;
        }
        currentPack = await response.json();
        renderPackEditor();
    } catch (error) {
        console.error('Failed to load pack:', error);
    }
}

function renderPackEditor() {
    if (!currentPack) return;

    // Pack name
    const nameInput = document.getElementById('pack-name');
    if (nameInput) {
        nameInput.value = currentPack.name;
    }

    // Stations list
    renderStationsList();
}

function renderStationsList() {
    const stationsList = document.getElementById('stations-list');
    if (!stationsList || !currentPack) return;

    if (currentPack.stations.length === 0) {
        stationsList.innerHTML = '<div class="empty-state">No stations yet. Add one below!</div>';
        return;
    }

    stationsList.innerHTML = currentPack.stations.map((station, index) => `
        <div class="station-item" data-station-id="${station.id}" data-index="${index}">
            <div class="drag-handle">&#9776;</div>
            <div class="station-info">
                <div class="name">${escapeHtml(station.name)}</div>
                <div class="url">${escapeHtml(station.url)}</div>
            </div>
            <div class="station-actions">
                <button class="edit-station-btn">Edit</button>
                <button class="delete-station-btn danger">Delete</button>
            </div>
        </div>
    `).join('');

    // Add event listeners
    stationsList.querySelectorAll('.station-item').forEach(item => {
        const stationId = item.dataset.stationId;
        const station = currentPack.stations.find(s => s.id === stationId);

        item.querySelector('.edit-station-btn')?.addEventListener('click', () => {
            showEditStationModal(station);
        });

        item.querySelector('.delete-station-btn')?.addEventListener('click', () => {
            showDeleteStationModal(station);
        });
    });
}

async function savePack() {
    const nameInput = document.getElementById('pack-name');
    if (!nameInput || !currentPackId) return;

    try {
        await fetch(`/api/packs/${currentPackId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: nameInput.value.trim() })
        });
    } catch (error) {
        console.error('Failed to save pack:', error);
    }
}

async function deletePack() {
    if (!currentPackId) return;

    try {
        await fetch(`/api/packs/${currentPackId}`, { method: 'DELETE' });
        window.location.href = '/packs';
    } catch (error) {
        console.error('Failed to delete pack:', error);
    }
}

async function addStation() {
    const nameInput = document.getElementById('new-station-name');
    const urlInput = document.getElementById('new-station-url');
    if (!nameInput || !urlInput || !currentPackId) return;

    const name = nameInput.value.trim();
    const url = urlInput.value.trim();
    if (!name || !url) return;

    try {
        const response = await fetch(`/api/packs/${currentPackId}/stations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url })
        });

        if (response.ok) {
            nameInput.value = '';
            urlInput.value = '';
            loadPack();
        }
    } catch (error) {
        console.error('Failed to add station:', error);
    }
}

function showEditStationModal(station) {
    editingStationId = station.id;
    document.getElementById('edit-station-name').value = station.name;
    document.getElementById('edit-station-url').value = station.url;
    document.getElementById('edit-station-modal').classList.add('active');
}

function closeEditStationModal() {
    editingStationId = null;
    document.getElementById('edit-station-modal').classList.remove('active');
}

async function saveStation() {
    if (!editingStationId || !currentPackId) return;

    const name = document.getElementById('edit-station-name').value.trim();
    const url = document.getElementById('edit-station-url').value.trim();
    if (!name || !url) return;

    try {
        await fetch(`/api/packs/${currentPackId}/stations/${editingStationId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url })
        });
        closeEditStationModal();
        loadPack();
    } catch (error) {
        console.error('Failed to save station:', error);
    }
}

function showDeleteStationModal(station) {
    deleteStationId = station.id;
    document.getElementById('delete-station-name').textContent = station.name;
    document.getElementById('delete-station-modal').classList.add('active');
}

function closeDeleteStationModal() {
    deleteStationId = null;
    document.getElementById('delete-station-modal').classList.remove('active');
}

async function confirmDeleteStation() {
    if (!deleteStationId || !currentPackId) return;

    try {
        await fetch(`/api/packs/${currentPackId}/stations/${deleteStationId}`, { method: 'DELETE' });
        closeDeleteStationModal();
        loadPack();
    } catch (error) {
        console.error('Failed to delete station:', error);
    }
}

// =============================================================================
// Settings Page
// =============================================================================

function initSettingsPage() {
    loadSettings();

    // Default volume slider
    const volumeSlider = document.getElementById('default-volume');
    const volumeValue = document.getElementById('default-volume-value');

    if (volumeSlider && volumeValue) {
        volumeSlider.addEventListener('input', (e) => {
            volumeValue.textContent = e.target.value;
        });
    }

    // Max volume slider
    const maxVolumeSlider = document.getElementById('max-volume');
    const maxVolumeValue = document.getElementById('max-volume-value');

    if (maxVolumeSlider && maxVolumeValue) {
        maxVolumeSlider.addEventListener('input', (e) => {
            maxVolumeValue.textContent = e.target.value;
        });
    }

    // Static volume slider
    const staticSlider = document.getElementById('static-volume');
    const staticValue = document.getElementById('static-volume-value');

    if (staticSlider && staticValue) {
        staticSlider.addEventListener('input', (e) => {
            staticValue.textContent = e.target.value;
        });
    }

    // Save button
    document.getElementById('save-settings-btn')?.addEventListener('click', saveSettings);
}

async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const settings = await response.json();

        const volumeSlider = document.getElementById('default-volume');
        const volumeValue = document.getElementById('default-volume-value');

        if (volumeSlider) volumeSlider.value = settings.default_volume;
        if (volumeValue) volumeValue.textContent = settings.default_volume;

        const maxVolumeSlider = document.getElementById('max-volume');
        const maxVolumeValue = document.getElementById('max-volume-value');

        if (maxVolumeSlider) maxVolumeSlider.value = settings.max_volume ?? 100;
        if (maxVolumeValue) maxVolumeValue.textContent = settings.max_volume ?? 100;

        const staticSlider = document.getElementById('static-volume');
        const staticValue = document.getElementById('static-volume-value');

        if (staticSlider) staticSlider.value = settings.static_volume ?? 75;
        if (staticValue) staticValue.textContent = settings.static_volume ?? 75;

        const loudnessCheckbox = document.getElementById('loudness-normalization');
        if (loudnessCheckbox) loudnessCheckbox.checked = settings.loudness_normalization ?? false;

        const autoStartCheckbox = document.getElementById('auto-start');
        if (autoStartCheckbox) autoStartCheckbox.checked = settings.auto_start ?? true;
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

async function saveSettings() {
    const volumeSlider = document.getElementById('default-volume');
    const maxVolumeSlider = document.getElementById('max-volume');
    const staticSlider = document.getElementById('static-volume');
    const loudnessCheckbox = document.getElementById('loudness-normalization');
    const autoStartCheckbox = document.getElementById('auto-start');
    const statusEl = document.getElementById('settings-status');

    const settings = {
        default_volume: parseInt(volumeSlider?.value || 50),
        max_volume: parseInt(maxVolumeSlider?.value || 100),
        static_volume: parseInt(staticSlider?.value || 75),
        loudness_normalization: loudnessCheckbox?.checked ?? false,
        auto_start: autoStartCheckbox?.checked ?? true
    };

    try {
        await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        if (statusEl) {
            statusEl.textContent = 'Settings saved & applied!';
            statusEl.style.color = 'var(--text-primary)';
            setTimeout(() => { statusEl.textContent = ''; }, 3000);
        }
    } catch (error) {
        console.error('Failed to save settings:', error);
        if (statusEl) {
            statusEl.textContent = 'Failed to save settings';
            statusEl.style.color = 'var(--danger)';
        }
    }
}

// =============================================================================
// Utility Functions
// =============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
