// Sample video data with real avatars and categories
const videos = [
    {
        id: 1,
        title: "Building a Modern Website in 2024 - Complete Tutorial",
        thumbnail: "https://picsum.photos/seed/code1/640/360",
        duration: "24:35",
        channelName: "CodeMaster Pro",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=CodeMaster",
        views: "1.2M views",
        postedAt: "2 days ago",
        category: "Programming"
    },
    {
        id: 2,
        title: "Top 10 Programming Languages to Learn This Year",
        thumbnail: "https://picsum.photos/seed/tech2/640/360",
        duration: "15:20",
        channelName: "Tech Trends",
        channelInitial: "T",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=TechTrends",
        views: "890K views",
        postedAt: "5 days ago",
        category: "Technology"
    },
    {
        id: 3,
        title: "Relaxing Music for Coding - 10 Hours Study Music",
        thumbnail: "https://picsum.photos/seed/lofi3/640/360",
        duration: "10:00:00",
        channelName: "LoFi Beats",
        channelInitial: "L",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=LoFi",
        views: "5.4M views",
        postedAt: "1 week ago",
        category: "Music"
    },
    {
        id: 4,
        title: "Building an AI Chatbot with Python - Full Guide",
        thumbnail: "https://picsum.photos/seed/python4/640/360",
        duration: "45:12",
        channelName: "Python Dev",
        channelInitial: "P",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=PythonDev",
        views: "2.1M views",
        postedAt: "3 days ago",
        category: "Programming"
    },
    {
        id: 5,
        title: "Epic Gaming Highlights - Best Moments Compilation",
        thumbnail: "https://picsum.photos/seed/game5/640/360",
        duration: "32:48",
        channelName: "Gaming Vault",
        channelInitial: "G",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=GamingVault",
        views: "3.8M views",
        postedAt: "1 day ago",
        category: "Gaming"
    },
    {
        id: 6,
        title: "Travel Vlog: Exploring Tokyo, Japan",
        thumbnail: "https://picsum.photos/seed/travel6/640/360",
        duration: "18:25",
        channelName: "Wanderlust",
        channelInitial: "W",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Wanderlust",
        views: "756K views",
        postedAt: "2 weeks ago",
        category: "Travel"
    },
    {
        id: 7,
        title: "Full Body Workout - No Equipment Needed",
        thumbnail: "https://picsum.photos/seed/fitness7/640/360",
        duration: "28:00",
        channelName: "FitLife",
        channelInitial: "F",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=FitLife",
        views: "1.9M views",
        postedAt: "4 days ago",
        category: "Fitness"
    },
    {
        id: 8,
        title: "Cooking Masterclass: Italian Pasta Recipes",
        thumbnail: "https://picsum.photos/seed/cooking8/640/360",
        duration: "22:15",
        channelName: "Chef's Kitchen",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=ChefKitchen",
        views: "543K views",
        postedAt: "1 week ago",
        category: "Cooking"
    },
    {
        id: 9,
        title: "Nature 4K - Relaxing Forest & Wildlife",
        thumbnail: "https://picsum.photos/seed/nature9/640/360",
        duration: "1:00:00",
        channelName: "Nature World",
        channelInitial: "N",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=NatureWorld",
        views: "8.2M views",
        postedAt: "3 weeks ago",
        category: "Education"
    },
    {
        id: 10,
        title: "JavaScript Crash Course - Learn in 60 Minutes",
        thumbnail: "https://picsum.photos/seed/js10/640/360",
        duration: "58:42",
        channelName: "Web Dev Simplified",
        channelInitial: "W",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=WebDev",
        views: "4.5M views",
        postedAt: "6 days ago",
        category: "Programming"
    },
    {
        id: 11,
        title: "Minecraft Build Challenge - 24 Hour Stream",
        thumbnail: "https://picsum.photos/seed/minecraft11/640/360",
        duration: "24:00:00",
        channelName: "Block Builder",
        channelInitial: "B",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=BlockBuilder",
        views: "12M views",
        postedAt: "5 hours ago",
        category: "Gaming"
    },
    {
        id: 12,
        title: "Space Documentary - Journey to the Edge of Universe",
        thumbnail: "https://picsum.photos/seed/space12/640/360",
        duration: "52:18",
        channelName: "Cosmos HD",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Cosmos",
        views: "6.7M views",
        postedAt: "2 weeks ago",
        category: "Education"
    },
    {
        id: 13,
        title: "LIVE: Championship Finals - Sports Highlights",
        thumbnail: "https://picsum.photos/seed/sports13/640/360",
        duration: "LIVE",
        channelName: "Sports Central",
        channelInitial: "S",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Sports",
        views: "250K watching",
        postedAt: "LIVE",
        category: "Sports"
    },
    {
        id: 14,
        title: "Breaking News: Tech Industry Updates",
        thumbnail: "https://picsum.photos/seed/news14/640/360",
        duration: "12:45",
        channelName: "News Today",
        channelInitial: "N",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=News",
        views: "420K views",
        postedAt: "1 hour ago",
        category: "News"
    },
    {
        id: 15,
        title: "Stand Up Comedy - Best of 2024",
        thumbnail: "https://picsum.photos/seed/comedy15/640/360",
        duration: "45:30",
        channelName: "Comedy Club",
        channelInitial: "C",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=Comedy",
        views: "2.3M views",
        postedAt: "3 days ago",
        category: "Comedy"
    },
    {
        id: 16,
        title: "iPhone 16 Pro Max - Full Review",
        thumbnail: "https://picsum.photos/seed/tech16/640/360",
        duration: "18:22",
        channelName: "Tech Unboxing",
        channelInitial: "T",
        channelAvatar: "https://api.dicebear.com/7.x/avataaars/svg?seed=TechUnbox",
        views: "1.8M views",
        postedAt: "1 day ago",
        category: "Technology"
    }
];

// Search suggestions data
const searchSuggestions = [
    { query: "build a website", icon: "fa-globe" },
    { query: "javascript tutorial", icon: "fa-code" },
    { query: "python for beginners", icon: "fa-python" },
    { query: "music relaxation", icon: "fa-music" },
    { query: "gaming highlights", icon: "fa-gamepad" },
    { query: "workout at home", icon: "fa-dumbbell" },
    { query: "travel japan", icon: "fa-plane" },
    { query: "cooking italian food", icon: "fa-utensils" },
    { query: "nature documentary", icon: "fa-leaf" },
    { query: "ai chatbot python", icon: "fa-robot" },
    { query: "web development", icon: "fa-laptop-code" },
    { query: "fitness motivation", icon: "fa-heart-pulse" },
    { query: "minecraft builds", icon: "fa-cubes" },
    { query: "space exploration", icon: "fa-rocket" },
    { query: "coding music", icon: "fa-headphones" },
    { query: "football highlights", icon: "fa-futbol" },
    { query: "news today", icon: "fa-newspaper" },
    { query: "comedy skits", icon: "fa-face-laugh" }
];

// Sidebar navigation data
const sidebarNavItems = [
    { id: 'home', icon: 'fa-house', label: 'Home', active: true },
    { id: 'shorts', icon: 'fa-play', label: 'Shorts' },
    { id: 'subscriptions', icon: 'fa-photo-video', label: 'Subscriptions' }
];

const sidebarSections = {
    you: [
        { icon: 'fa-user', label: 'Your Channel' },
        { icon: 'fa-history', label: 'History' },
        { icon: 'fa-clock', label: 'Watch Later' },
        { icon: 'fa-thumbs-up', label: 'Liked Videos' },
        { icon: 'fa-play-circle', label: 'Your Videos' },
        { icon: 'fa-list', label: 'Your Playlists' }
    ],
    subscriptions: [
        { name: 'CodeMaster Pro', avatar: 'CodeMaster' },
        { name: 'Tech Trends', avatar: 'TechTrends' },
        { name: 'LoFi Beats', avatar: 'LoFi' },
        { name: 'Python Dev', avatar: 'PythonDev' },
        { name: 'Gaming Vault', avatar: 'GamingVault' },
        { name: 'Wanderlust', avatar: 'Wanderlust' }
    ],
    explore: [
        { icon: 'fa-fire', label: 'Trending' },
        { icon: 'fa-music', label: 'Music' },
        { icon: 'fa-gamepad', label: 'Gaming' },
        { icon: 'fa-trophy', label: 'Sports' },
        { icon: 'fa-newspaper', label: 'News' },
        { icon: 'fa-lightbulb', label: 'Learning' }
    ],
    moreFromYoutube: [
        { icon: 'fa-youtube', label: 'YouTube Premium' },
        { icon: 'fa-headphones', label: 'YouTube Music' },
        { icon: 'fa-child', label: 'YouTube Kids' }
    ]
};

// DOM Elements
const videoGrid = document.getElementById('videoGrid');
const menuBtn = document.getElementById('menuBtn');
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('mainContent');
const themeBtn = document.getElementById('themeBtn');
const searchInput = document.getElementById('searchInput');
const searchSuggestionsEl = document.getElementById('searchSuggestions');
const filterChips = document.querySelectorAll('.filter-chip');
const videoModal = document.getElementById('videoModal');
const closeModal = document.getElementById('closeModal');
const modalOverlay = document.getElementById('modalOverlay');
const modalVideoInfo = document.getElementById('modalVideoInfo');
const playerPlaceholder = document.getElementById('playerPlaceholder');

// State
let isDarkMode = false;
let isSidebarCollapsed = false;
let currentVideo = null;
let isPlaying = false;
let likedVideos = new Set();
let subscribedChannels = new Set();
let savedVideos = new Set();
let currentCategory = 'All';
let activeNavItem = 'home';

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadTheme();
    loadSidebarState();
    loadSavedData();
    renderVideos(videos);
    setupEventListeners();
    setupSidebarNavigation();
});

// Setup all event listeners
function setupEventListeners() {
    // Menu button
    menuBtn.addEventListener('click', toggleSidebar);
    
    // Theme button
    themeBtn.addEventListener('click', toggleTheme);
    
    // Search
    const searchBtn = document.querySelector('.search-btn');
    searchBtn.addEventListener('click', performSearch);
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') performSearch();
    });
    searchInput.addEventListener('input', handleSearchInput);
    searchInput.addEventListener('focus', () => {
        if (searchInput.value.trim()) showSuggestions(searchInput.value);
    });
    
    // Close suggestions on outside click
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.header-center')) hideSuggestions();
    });
    
    // Filter chips
    filterChips.forEach(chip => {
        chip.addEventListener('click', () => handleFilterClick(chip));
    });
    
    // Modal
    closeModal.addEventListener('click', closeVideoModal);
    modalOverlay.addEventListener('click', closeVideoModal);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeVideoModal();
    });
    
    // Mic button
    const micBtn = document.querySelector('.mic-btn');
    micBtn.addEventListener('click', handleVoiceSearch);
    
    // Window resize
    window.addEventListener('resize', handleResize);
    
    // Keyboard navigation
    setupKeyboardNavigation();
    
    // Logo click - reset
    document.querySelector('.logo').addEventListener('click', (e) => {
        e.preventDefault();
        resetView();
    });
}

// Sidebar toggle
function toggleSidebar() {
    if (window.innerWidth <= 900) {
        sidebar.classList.toggle('visible');
    } else {
        isSidebarCollapsed = !isSidebarCollapsed;
        sidebar.classList.toggle('mini', isSidebarCollapsed);
        mainContent.classList.toggle('mini-sidebar', isSidebarCollapsed);
        localStorage.setItem('sidebarCollapsed', isSidebarCollapsed);
    }
}

// Setup sidebar navigation
function setupSidebarNavigation() {
    // Top nav items
    document.querySelectorAll('.sidebar-nav > .nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const href = item.getAttribute('href');
            if (href === '#') {
                // Handle navigation
                const icon = item.querySelector('i');
                const label = item.querySelector('span').textContent.toLowerCase();
                
                // Update active state
                document.querySelectorAll('.sidebar-nav > .nav-item').forEach(i => i.classList.remove('active'));
                document.querySelectorAll('.content .filters + .video-grid .filter-chip').forEach(c => c.classList.remove('active'));
                item.classList.add('active');
                
                if (label === 'home') {
                    currentCategory = 'All';
                    document.querySelector('.filter-chip:first-child').classList.add('active');
                    renderVideos(videos);
                } else if (label === 'shorts') {
                    currentCategory = 'Shorts';
                    renderVideos(videos.filter(v => v.category === 'Gaming' || v.category === 'Comedy'));
                } else if (label === 'subscriptions') {
                    // Show subscription videos
                    const subscribedVideos = videos.filter(v => subscribedChannels.has(v.channelName));
                    if (subscribedVideos.length > 0) {
                        renderVideos(subscribedVideos);
                    } else {
                        renderVideos(videos.slice(0, 6));
                    }
                }
                
                // Close mobile sidebar
                if (window.innerWidth <= 900) {
                    sidebar.classList.remove('visible');
                }
            }
        });
    });
    
    // You section items
    document.querySelectorAll('.sidebar-section .nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const label = item.querySelector('span')?.textContent || item.textContent;
            handleSidebarAction(label);
            
            if (window.innerWidth <= 900) {
                sidebar.classList.remove('visible');
            }
        });
    });
}

// Handle sidebar actions
function handleSidebarAction(action) {
    const actionLower = action.toLowerCase();
    
    if (actionLower.includes('channel')) {
        showNotification('Your Channel', 'Channel page coming soon!');
    } else if (actionLower.includes('history')) {
        showNotification('History', 'Showing watch history');
    } else if (actionLower.includes('watch later')) {
        showNotification('Watch Later', 'Your watch later list is empty');
    } else if (actionLower.includes('liked')) {
        const liked = videos.filter(v => likedVideos.has(v.id));
        if (liked.length > 0) {
            renderVideos(liked);
        } else {
            showNotification('Liked Videos', 'No liked videos yet');
        }
    } else if (actionLower.includes('playlist')) {
        showNotification('Playlists', 'Your playlists are empty');
    } else if (actionLower.includes('trending')) {
        currentCategory = 'Trending';
        renderVideos(videos.slice(0, 8));
    } else if (actionLower.includes('music')) {
        currentCategory = 'Music';
        renderVideos(videos.filter(v => v.category === 'Music'));
    } else if (actionLower.includes('gaming')) {
        currentCategory = 'Gaming';
        renderVideos(videos.filter(v => v.category === 'Gaming'));
    } else if (actionLower.includes('sports')) {
        currentCategory = 'Sports';
        renderVideos(videos.filter(v => v.category === 'Sports'));
    } else if (actionLower.includes('news')) {
        currentCategory = 'News';
        renderVideos(videos.filter(v => v.category === 'News'));
    } else if (actionLower.includes('learning')) {
        currentCategory = 'Learning';
        renderVideos(videos.filter(v => v.category === 'Education'));
    } else if (actionLower.includes('premium')) {
        showNotification('YouTube Premium', 'Premium features coming soon!');
    } else if (actionLower.includes('kids')) {
        showNotification('YouTube Kids', 'Redirecting to YouTube Kids...');
    }
}

// Show notification (simple alert replacement)
function showNotification(title, message) {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = 'notification-toast';
    notification.innerHTML = `
        <div class="notification-content">
            <strong>${title}</strong>
            <p>${message}</p>
        </div>
        <button class="notification-close"><i class="fas fa-times"></i></button>
    `;
    document.body.appendChild(notification);
    
    // Add styles dynamically
    notification.style.cssText = `
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 16px 20px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        z-index: 2000;
        animation: slideUp 0.3s ease;
    `;
    
    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideUp {
            from { opacity: 0; transform: translateX(-50%) translateY(20px); }
            to { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
    `;
    document.head.appendChild(style);
    
    // Close button
    notification.querySelector('.notification-close').addEventListener('click', () => {
        notification.remove();
    });
    
    // Auto close after 3 seconds
    setTimeout(() => {
        if (notification.parentElement) notification.remove();
    }, 3000);
}

// Reset view to home
function resetView() {
    currentCategory = 'All';
    searchInput.value = '';
    filterChips.forEach(c => c.classList.remove('active'));
    filterChips[0].classList.add('active');
    document.querySelectorAll('.sidebar-nav > .nav-item').forEach(i => i.classList.remove('active'));
    document.querySelector('.sidebar-nav > .nav-item:first-child').classList.add('active');
    renderVideos(videos);
}

// Theme toggle
function toggleTheme() {
    isDarkMode = !isDarkMode;
    document.documentElement.setAttribute('data-theme', isDarkMode ? 'dark' : 'light');
    themeBtn.querySelector('i').className = isDarkMode ? 'fas fa-sun' : 'fas fa-moon';
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
}

// Load theme
function loadTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        isDarkMode = true;
        document.documentElement.setAttribute('data-theme', 'dark');
        themeBtn.querySelector('i').className = 'fas fa-sun';
    }
}

// Load sidebar state
function loadSidebarState() {
    const collapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (collapsed && window.innerWidth > 900) {
        isSidebarCollapsed = true;
        sidebar.classList.add('mini');
        mainContent.classList.add('mini-sidebar');
    }
}

// Load saved data
function loadSavedData() {
    const liked = localStorage.getItem('likedVideos');
    if (liked) likedVideos = new Set(JSON.parse(liked));
    
    const subscribed = localStorage.getItem('subscribedChannels');
    if (subscribed) subscribedChannels = new Set(JSON.parse(subscribed));
    
    const saved = localStorage.getItem('savedVideos');
    if (saved) savedVideos = new Set(JSON.parse(saved));
}

// Render videos
function renderVideos(videoList) {
    videoGrid.innerHTML = '';
    
    if (videoList.length === 0) {
        videoGrid.innerHTML = `
            <div class="no-results">
                <i class="fas fa-search"></i>
                <h3>No videos found</h3>
                <p>Try different keywords or browse categories</p>
            </div>
        `;
        return;
    }
    
    videoList.forEach((video, index) => {
        const isLiked = likedVideos.has(video.id);
        const isLive = video.postedAt === 'LIVE';
        
        const videoCard = document.createElement('button');
        videoCard.className = 'video-card';
        videoCard.dataset.id = video.id;
        videoCard.innerHTML = `
            <div class="thumbnail-container">
                <img src="${video.thumbnail}" alt="${video.title}" loading="lazy">
                <span class="duration ${isLive ? 'live' : ''}">${video.duration}</span>
                ${isLive ? '<span class="live-badge">LIVE</span>' : ''}
            </div>
            <div class="video-info">
                <div class="channel-avatar">
                    <img src="${video.channelAvatar}" alt="${video.channelName}">
                </div>
                <div class="video-details">
                    <h3 class="video-title">${video.title}</h3>
                    <p class="channel-name">${video.channelName}</p>
                    <p class="video-meta">${video.views} • ${video.postedAt}</p>
                    <div class="video-actions">
                        <button class="action-btn like-btn ${isLiked ? 'liked' : ''}" data-id="${video.id}">
                            <i class="fas fa-thumbs-up"></i>
                            <span>${isLiked ? 'Liked' : 'Like'}</span>
                        </button>
                        <button class="action-btn share-btn" data-id="${video.id}">
                            <i class="fas fa-share"></i>
                            <span>Share</span>
                        </button>
                        <button class="action-btn subscribe ${subscribedChannels.has(video.channelName) ? 'subscribed' : ''}" data-channel="${video.channelName}">
                            <i class="fas fa-bell"></i>
                            <span>${subscribedChannels.has(video.channelName) ? 'Subscribed' : 'Subscribe'}</span>
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        // Video click
        videoCard.addEventListener('click', (e) => {
            if (!e.target.closest('.action-btn')) {
                openVideoModal(video);
            }
        });
        
        videoGrid.appendChild(videoCard);
    });
    
    addActionListeners();
}

// Add action button listeners
function addActionListeners() {
    // Like buttons
    document.querySelectorAll('.like-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const videoId = parseInt(btn.dataset.id);
            toggleLike(videoId, btn);
        });
    });
    
    // Share buttons
    document.querySelectorAll('.share-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            shareVideo(btn.dataset.id);
        });
    });
    
    // Subscribe buttons
    document.querySelectorAll('.action-btn.subscribe').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSubscribe(btn.dataset.channel, btn);
        });
    });
}

// Toggle like
function toggleLike(videoId, btn) {
    if (likedVideos.has(videoId)) {
        likedVideos.delete(videoId);
        btn.classList.remove('liked');
        btn.querySelector('span').textContent = 'Like';
    } else {
        likedVideos.add(videoId);
        btn.classList.add('liked');
        btn.querySelector('span').textContent = 'Liked';
    }
    localStorage.setItem('likedVideos', JSON.stringify([...likedVideos]));
}

// Share video
function shareVideo(videoId) {
    const video = videos.find(v => v.id === parseInt(videoId));
    if (navigator.share) {
        navigator.share({ title: video.title, text: `Check out: ${video.title}`, url: window.location.href });
    } else {
        navigator.clipboard.writeText(window.location.href);
        showNotification('Shared', 'Link copied to clipboard!');
    }
}

// Toggle subscribe
function toggleSubscribe(channelName, btn) {
    if (subscribedChannels.has(channelName)) {
        subscribedChannels.delete(channelName);
        btn.classList.remove('subscribed');
        btn.querySelector('span').textContent = 'Subscribe';
    } else {
        subscribedChannels.add(channelName);
        btn.classList.add('subscribed');
        btn.querySelector('span').textContent = 'Subscribed';
        showNotification('Subscribed', `You're now subscribed to ${channelName}`);
    }
    localStorage.setItem('subscribedChannels', JSON.stringify([...subscribedChannels]));
}

// Filter click handler
function handleFilterClick(chip) {
    filterChips.forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    
    const category = chip.textContent;
    currentCategory = category;
    
    if (category === 'All') {
        renderVideos(videos);
    } else {
        const filtered = videos.filter(v => v.category === category);
        if (filtered.length > 0) {
            renderVideos(filtered);
        } else {
            // Shuffle for demo
            renderVideos([...videos].sort(() => Math.random() - 0.5));
        }
    }
}

// Search handlers
function handleSearchInput(e) {
    const query = e.target.value.toLowerCase().trim();
    if (query.length > 0) {
        showSuggestions(query);
    } else {
        hideSuggestions();
    }
}

function showSuggestions(query) {
    const filtered = searchSuggestions.filter(s => s.query.toLowerCase().includes(query));
    
    if (filtered.length === 0) {
        hideSuggestions();
        return;
    }
    
    searchSuggestionsEl.innerHTML = filtered.map(s => `
        <div class="suggestion-item" data-query="${s.query}">
            <i class="fas ${s.icon}"></i>
            <span>${s.query}</span>
        </div>
    `).join('');
    
    searchSuggestionsEl.classList.add('active');
    
    document.querySelectorAll('.suggestion-item').forEach(item => {
        item.addEventListener('click', () => {
            searchInput.value = item.dataset.query;
            performSearch();
        });
    });
}

function hideSuggestions() {
    searchSuggestionsEl.classList.remove('active');
}

function performSearch() {
    const query = searchInput.value.toLowerCase().trim();
    hideSuggestions();
    
    if (!query) {
        renderVideos(videos);
        return;
    }
    
    const filtered = videos.filter(video => 
        video.title.toLowerCase().includes(query) ||
        video.channelName.toLowerCase().includes(query) ||
        video.category.toLowerCase().includes(query)
    );
    
    renderVideos(filtered);
}

// Voice search
function handleVoiceSearch() {
    const micBtn = document.querySelector('.mic-btn');
    micBtn.classList.add('listening');
    showNotification('Voice Search', 'Listening... (simulated)');
    
    setTimeout(() => {
        micBtn.classList.remove('listening');
    }, 2000);
}

// Resize handler
function handleResize() {
    if (window.innerWidth > 900) {
        sidebar.classList.remove('visible');
    }
}

// Keyboard navigation
function setupKeyboardNavigation() {
    let focusedIndex = -1;
    
    videoGrid.addEventListener('keydown', (e) => {
        const cards = document.querySelectorAll('.video-card');
        if (!cards.length) return;
        
        const totalCards = cards.length;
        const columns = Math.floor(videoGrid.offsetWidth / 340) || 1;
        
        switch(e.key) {
            case 'ArrowRight':
                e.preventDefault();
                focusedIndex = Math.min(focusedIndex + 1, totalCards - 1);
                cards[focusedIndex]?.focus();
                break;
            case 'ArrowLeft':
                e.preventDefault();
                focusedIndex = Math.max(focusedIndex - 1, 0);
                cards[focusedIndex]?.focus();
                break;
            case 'ArrowDown':
                e.preventDefault();
                focusedIndex = Math.min(focusedIndex + columns, totalCards - 1);
                cards[focusedIndex]?.focus();
                break;
            case 'ArrowUp':
                e.preventDefault();
                focusedIndex = Math.max(focusedIndex - columns, 0);
                cards[focusedIndex]?.focus();
                break;
            case 'Enter':
                if (focusedIndex >= 0) {
                    const videoId = parseInt(cards[focusedIndex].dataset.id);
                    const video = videos.find(v => v.id === videoId);
                    openVideoModal(video);
                }
                break;
            case 'Home':
                e.preventDefault();
                focusedIndex = 0;
                cards[0]?.focus();
                break;
            case 'End':
                e.preventDefault();
                focusedIndex = totalCards - 1;
                cards[focusedIndex]?.focus();
                break;
        }
    });
}

// Video Modal Functions
function openVideoModal(video) {
    currentVideo = video;
    isPlaying = false;
    
    const isLiked = likedVideos.has(video.id);
    const isSubscribed = subscribedChannels.has(video.channelName);
    const isSaved = savedVideos.has(video.id);
    const isLive = video.postedAt === 'LIVE';
    
    modalVideoInfo.innerHTML = `
        <h2 class="modal-video-title">${video.title}</h2>
        <div class="modal-video-stats">
            <span class="modal-views">${video.views} • ${video.postedAt}</span>
            <div class="modal-buttons">
                <button class="modal-btn like-btn ${isLiked ? 'active' : ''}" id="modalLike">
                    <i class="fas fa-thumbs-up"></i>
                    <span>${isLiked ? 'Liked' : 'Like'}</span>
                </button>
                <button class="modal-btn" id="modalDislike">
                    <i class="fas fa-thumbs-down"></i>
                    <span>Dislike</span>
                </button>
                <button class="modal-btn" id="modalShare">
                    <i class="fas fa-share"></i>
                    <span>Share</span>
                </button>
                <button class="modal-btn save-btn ${isSaved ? 'active' : ''}" id="modalSave">
                    <i class="fas fa-bookmark"></i>
                    <span>${isSaved ? 'Saved' : 'Save'}</span>
                </button>
            </div>
        </div>
        <div class="modal-channel-info">
            <div class="modal-channel-avatar">
                <img src="${video.channelAvatar}" alt="${video.channelName}">
            </div>
            <div class="modal-channel-details">
                <div class="modal-channel-name">${video.channelName}</div>
                <div class="modal-channel-subs">1.2M subscribers</div>
            </div>
            <button class="modal-subscribe-btn ${isSubscribed ? 'subscribed' : ''}" id="modalSubscribe">
                ${isSubscribed ? 'Subscribed' : 'Subscribe'}
            </button>
        </div>
    `;
    
    // Modal button handlers
    document.getElementById('modalLike').addEventListener('click', function() {
        this.classList.toggle('active');
        const isActive = this.classList.contains('active');
        this.querySelector('span').textContent = isActive ? 'Liked' : 'Like';
        toggleLike(video.id, this);
    });
    
    document.getElementById('modalDislike').addEventListener('click', function() {
        this.classList.toggle('active');
    });
    
    document.getElementById('modalShare').addEventListener('click', () => shareVideo(video.id));
    
    document.getElementById('modalSave').addEventListener('click', function() {
        this.classList.toggle('active');
        const isActive = this.classList.contains('active');
        this.querySelector('span').textContent = isActive ? 'Saved' : 'Save';
        
        if (isActive) {
            savedVideos.add(video.id);
        } else {
            savedVideos.delete(video.id);
        }
        localStorage.setItem('savedVideos', JSON.stringify([...savedVideos]));
    });
    
    document.getElementById('modalSubscribe').addEventListener('click', function() {
        this.classList.toggle('subscribed');
        const isSubscribed = this.classList.contains('subscribed');
        this.textContent = isSubscribed ? 'Subscribed' : 'Subscribe';
        toggleSubscribe(video.channelName, this);
    });
    
    playerPlaceholder.innerHTML = `
        <i class="fas fa-play-circle"></i>
        <p>${isLive ? 'Watch Live' : 'Click to play video'}</p>
    `;
    
    videoModal.classList.add('active');
    document.body.style.overflow = 'hidden';
    playerPlaceholder.onclick = togglePlay;
}

function togglePlay() {
    isPlaying = !isPlaying;
    playerPlaceholder.innerHTML = isPlaying 
        ? `<i class="fas fa-pause-circle"></i><p>Playing...</p>`
        : `<i class="fas fa-play-circle"></i><p>Click to play video</p>`;
}

function closeVideoModal() {
    videoModal.classList.remove('active');
    document.body.style.overflow = '';
    currentVideo = null;
    isPlaying = false;
}
