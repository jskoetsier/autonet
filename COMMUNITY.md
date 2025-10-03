# AutoNet Community Contributions

## 🤝 Welcome Contributors!

AutoNet v2.0 is designed with extensibility in mind. We welcome community contributions, especially for multi-vendor support and advanced features.

## 🔌 Multi-Vendor Plugin Opportunities

The following vendor plugins are ready for community implementation:

### 🚀 **FRRouting (FRR)**
- **Status**: 🔮 Placeholder ready
- **File**: `plugins/vendors/frr.py`
- **Features needed**: BGP config generation, vtysh integration, route maps
- **Difficulty**: ⭐⭐⭐ (Medium)

### 🚀 **Cisco IOS/XR**
- **Status**: 🔮 Placeholder ready  
- **File**: `plugins/vendors/cisco.py`
- **Features needed**: IOS/XR BGP configs, route policies, validation
- **Difficulty**: ⭐⭐⭐⭐ (Advanced)

### 🚀 **Juniper JunOS**
- **Status**: 🔮 Placeholder ready
- **File**: `plugins/vendors/juniper.py`
- **Features needed**: JunOS BGP configs, policy statements, commit/rollback
- **Difficulty**: ⭐⭐⭐⭐ (Advanced)

### 🚀 **OpenBGPD**
- **Status**: 🔮 Placeholder ready
- **File**: `plugins/vendors/openbgpd.py`
- **Features needed**: OpenBGPD configs, bgpctl integration, prefix sets
- **Difficulty**: ⭐⭐⭐ (Medium)

### 🚀 **ExaBGP**
- **Status**: 🔮 Placeholder ready
- **File**: `plugins/vendors/exabgp.py`
- **Features needed**: Software-defined BGP, Python API, dynamic routes
- **Difficulty**: ⭐⭐⭐⭐⭐ (Expert)

## 🛠️ How to Contribute

### 1. Choose a Plugin
Pick a vendor plugin from the list above that matches your expertise.

### 2. Implement the Plugin
Each placeholder includes:
- Base plugin structure
- Required methods to implement
- Configuration examples
- Capability definitions

### 3. Key Methods to Implement
```python
def initialize(self) -> bool:
    # Check if vendor tools are available
    # Validate configuration
    # Return True if ready

def generate_config(self, peer_info, template_vars) -> str:
    # Generate vendor-specific BGP configuration
    # Use templates or direct generation
    # Return configuration string

def validate_config(self, config_content) -> bool:
    # Validate generated configuration
    # Use vendor tools (e.g., syntax check)
    # Return True if valid
```

### 4. Testing
```bash
# Test your plugin
./autonet.py peer-config --list-vendors  # Should show your plugin
./autonet.py peer-config --asn AS64512 --vendor your-vendor
```

### 5. Submit Pull Request
- Fork the repository
- Create feature branch: `git checkout -b feature/vendor-xyz`
- Implement and test your plugin
- Submit pull request with documentation

## 📋 Contribution Guidelines

### Code Standards
- Follow existing code style (Black formatting)
- Add comprehensive type hints
- Include proper error handling
- Add logging throughout

### Documentation
- Update plugin docstrings
- Add configuration examples
- Include troubleshooting notes
- Update this COMMUNITY.md

### Testing
- Add unit tests for your plugin
- Test with real vendor equipment if possible
- Include configuration validation tests

## 🏆 Recognition

Contributors will be:
- Listed in project credits
- Recognized in release notes
- Given maintainer status for their plugins

## 💬 Getting Help

- **Issues**: Open GitHub issues for questions
- **Discussions**: Use GitHub Discussions for design questions
- **Documentation**: Check existing BIRD2 plugin as reference

## 🎯 Priority Contributions

1. **FRRouting**: High community interest
2. **Cisco IOS**: Enterprise demand
3. **OpenBGPD**: BSD community support
4. **Juniper**: Enterprise networking
5. **ExaBGP**: Software-defined networking

---

**Ready to contribute?** Start with FRRouting for a medium-difficulty introduction to the plugin system!

**Questions?** Open a GitHub issue with the "community" label.