#!/usr/bin/env python3
"""
BGP Communities Support for AutoNet

Enhanced support for traditional BGP communities and RFC 8092 Large Communities.
Includes validation, parsing, and formatting utilities.
"""

import re
import logging
from typing import List, Dict, Any, Union, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CommunityType(Enum):
    """Types of BGP communities"""
    STANDARD = "standard"        # 16:16 format (RFC 1997)
    EXTENDED = "extended"        # Various formats (RFC 4360) 
    LARGE = "large"             # ASN:LocalData1:LocalData2 (RFC 8092)


@dataclass
class BGPCommunity:
    """BGP Community representation"""
    community_type: CommunityType
    value: str
    parsed_value: Tuple[int, ...]
    
    def __str__(self) -> str:
        return self.value
    
    def __repr__(self) -> str:
        return f"BGPCommunity({self.community_type.value}, {self.value})"


class BGPCommunityManager:
    """
    Manager for BGP communities with support for:
    - Traditional communities (16:16)
    - Large communities (32:32:32) 
    - Well-known communities
    - Community validation and parsing
    """
    
    # Well-known communities (RFC 1997)
    WELL_KNOWN_COMMUNITIES = {
        "NO_EXPORT": "65535:65281",
        "NO_ADVERTISE": "65535:65282", 
        "NO_EXPORT_SUBCONFED": "65535:65283",
        "BLACKHOLE": "65535:666",  # RFC 7999
    }
    
    def __init__(self):
        self.communities: List[BGPCommunity] = []
    
    def validate_standard_community(self, community: str) -> bool:
        """
        Validate standard BGP community format (16:16)
        
        Args:
            community: Community string (e.g., "64512:100")
            
        Returns:
            True if valid standard community
        """
        try:
            # Standard community format: ASN:VALUE (both 16-bit)
            if not re.match(r'^\d+:\d+$', community):
                return False
            
            parts = community.split(':')
            if len(parts) != 2:
                return False
            
            asn, value = int(parts[0]), int(parts[1])
            
            # Both parts must fit in 16 bits (0-65535)
            if not (0 <= asn <= 65535 and 0 <= value <= 65535):
                return False
            
            return True
            
        except (ValueError, TypeError):
            return False
    
    def validate_large_community(self, community: str) -> bool:
        """
        Validate large BGP community format (32:32:32) per RFC 8092
        
        Args:
            community: Community string (e.g., "64512:1:100")
            
        Returns:
            True if valid large community
        """
        try:
            # Large community format: ASN:LocalData1:LocalData2 (all 32-bit)
            if not re.match(r'^\d+:\d+:\d+$', community):
                return False
            
            parts = community.split(':')
            if len(parts) != 3:
                return False
            
            asn, local1, local2 = int(parts[0]), int(parts[1]), int(parts[2])
            
            # All parts must fit in 32 bits (0-4294967295)
            max_32bit = 4294967295
            if not (0 <= asn <= max_32bit and 0 <= local1 <= max_32bit and 0 <= local2 <= max_32bit):
                return False
            
            return True
            
        except (ValueError, TypeError):
            return False
    
    def validate_community(self, community: str) -> Tuple[bool, CommunityType]:
        """
        Validate any BGP community format and return its type
        
        Args:
            community: Community string
            
        Returns:
            Tuple of (is_valid, community_type)
        """
        # Check for well-known communities by name
        if community.upper() in self.WELL_KNOWN_COMMUNITIES:
            return True, CommunityType.STANDARD
        
        # Check for large community format first (3 parts)
        if ':' in community and len(community.split(':')) == 3:
            if self.validate_large_community(community):
                return True, CommunityType.LARGE
            else:
                return False, CommunityType.LARGE
        
        # Check for standard community format (2 parts)
        elif ':' in community and len(community.split(':')) == 2:
            if self.validate_standard_community(community):
                return True, CommunityType.STANDARD
            else:
                return False, CommunityType.STANDARD
        
        return False, CommunityType.STANDARD
    
    def parse_community(self, community: str) -> Optional[BGPCommunity]:
        """
        Parse a community string into a BGPCommunity object
        
        Args:
            community: Community string to parse
            
        Returns:
            BGPCommunity object or None if invalid
        """
        # Handle well-known communities
        if community.upper() in self.WELL_KNOWN_COMMUNITIES:
            actual_value = self.WELL_KNOWN_COMMUNITIES[community.upper()]
            parts = tuple(int(x) for x in actual_value.split(':'))
            return BGPCommunity(
                community_type=CommunityType.STANDARD,
                value=actual_value,
                parsed_value=parts
            )
        
        is_valid, comm_type = self.validate_community(community)
        if not is_valid:
            return None
        
        try:
            parts = tuple(int(x) for x in community.split(':'))
            return BGPCommunity(
                community_type=comm_type,
                value=community,
                parsed_value=parts
            )
        except ValueError:
            return None
    
    def add_community(self, community: str) -> bool:
        """
        Add a community to the manager
        
        Args:
            community: Community string to add
            
        Returns:
            True if successfully added
        """
        parsed = self.parse_community(community)
        if parsed:
            self.communities.append(parsed)
            return True
        return False
    
    def get_communities_by_type(self, community_type: CommunityType) -> List[BGPCommunity]:
        """Get all communities of a specific type"""
        return [c for c in self.communities if c.community_type == community_type]
    
    def format_for_vendor(self, vendor: str, community_type: CommunityType = None) -> List[str]:
        """
        Format communities for specific vendor syntax
        
        Args:
            vendor: Vendor name (bird, cisco, etc.)
            community_type: Filter by community type (optional)
            
        Returns:
            List of formatted community strings
        """
        communities = self.communities
        if community_type:
            communities = self.get_communities_by_type(community_type)
        
        if vendor.lower() == "bird":
            return self._format_bird_communities(communities)
        elif vendor.lower() == "cisco":
            return self._format_cisco_communities(communities)
        elif vendor.lower() == "frr":
            return self._format_frr_communities(communities)
        else:
            # Generic format
            return [c.value for c in communities]
    
    def _format_bird_communities(self, communities: List[BGPCommunity]) -> List[str]:
        """Format communities for BIRD router"""
        formatted = []
        
        for comm in communities:
            if comm.community_type == CommunityType.STANDARD:
                # BIRD format: (asn, value)
                asn, value = comm.parsed_value
                formatted.append(f"({asn}, {value})")
            elif comm.community_type == CommunityType.LARGE:
                # BIRD large community format: (asn, local1, local2)
                asn, local1, local2 = comm.parsed_value
                formatted.append(f"({asn}, {local1}, {local2})")
        
        return formatted
    
    def _format_cisco_communities(self, communities: List[BGPCommunity]) -> List[str]:
        """Format communities for Cisco routers"""
        formatted = []
        
        for comm in communities:
            if comm.community_type == CommunityType.STANDARD:
                # Cisco format: ASN:VALUE
                formatted.append(comm.value)
            elif comm.community_type == CommunityType.LARGE:
                # Cisco large community format: large:ASN:LOCAL1:LOCAL2
                asn, local1, local2 = comm.parsed_value
                formatted.append(f"large:{asn}:{local1}:{local2}")
        
        return formatted
    
    def _format_frr_communities(self, communities: List[BGPCommunity]) -> List[str]:
        """Format communities for FRRouting"""
        formatted = []
        
        for comm in communities:
            if comm.community_type == CommunityType.STANDARD:
                # FRR format: ASN:VALUE
                formatted.append(comm.value)
            elif comm.community_type == CommunityType.LARGE:
                # FRR large community format: large:ASN:LOCAL1:LOCAL2
                asn, local1, local2 = comm.parsed_value
                formatted.append(f"large:{asn}:{local1}:{local2}")
        
        return formatted
    
    def generate_blackhole_communities(self, asn: int, use_large: bool = True) -> List[str]:
        """
        Generate blackhole communities for the specified ASN
        
        Args:
            asn: ASN number (supports 32-bit)
            use_large: Whether to use large communities for 32-bit ASNs
            
        Returns:
            List of blackhole community strings
        """
        communities = []
        
        # Traditional blackhole community (RFC 7999)
        communities.append("65535:666")
        
        # ASN-specific blackhole community
        if asn <= 65535:
            # 16-bit ASN - use standard community
            communities.append(f"{asn}:666")
        else:
            # 32-bit ASN - use large community if requested
            if use_large:
                communities.append(f"{asn}:666:0")
            # Also provide a traditional community with ASN encoded
            # Some operators use high-order/low-order encoding
            high = asn >> 16
            low = asn & 0xFFFF
            communities.append(f"{high}:{low}")
        
        return communities
    
    def validate_asn_32bit(self, asn: Union[str, int]) -> bool:
        """
        Validate 32-bit ASN number
        
        Args:
            asn: ASN as string (with or without AS prefix) or integer
            
        Returns:
            True if valid 32-bit ASN
        """
        try:
            if isinstance(asn, str):
                # Remove AS prefix if present
                if asn.upper().startswith('AS'):
                    asn_num = int(asn[2:])
                else:
                    asn_num = int(asn)
            else:
                asn_num = int(asn)
            
            # Valid 32-bit ASN range (excluding reserved ranges)
            # 0 is reserved, 23456 is reserved for AS_TRANS, 4294967295 is reserved
            if asn_num == 0 or asn_num == 23456 or asn_num == 4294967295:
                return False
            
            # Valid range: 1-4294967294
            return 1 <= asn_num <= 4294967294
            
        except (ValueError, TypeError):
            return False
    
    def is_32bit_asn(self, asn: Union[str, int]) -> bool:
        """
        Check if ASN is a 32-bit ASN (> 65535)
        
        Args:
            asn: ASN as string or integer
            
        Returns:
            True if 32-bit ASN
        """
        try:
            if isinstance(asn, str):
                if asn.upper().startswith('AS'):
                    asn_num = int(asn[2:])
                else:
                    asn_num = int(asn)
            else:
                asn_num = int(asn)
            
            return asn_num > 65535
            
        except (ValueError, TypeError):
            return False


def create_community_manager() -> BGPCommunityManager:
    """Factory function to create a BGP community manager"""
    return BGPCommunityManager()


# Utility functions for backward compatibility
def validate_32bit_asn(asn: Union[str, int]) -> bool:
    """Validate 32-bit ASN - utility function"""
    manager = BGPCommunityManager()
    return manager.validate_asn_32bit(asn)


def validate_large_community(community: str) -> bool:
    """Validate large community - utility function"""
    manager = BGPCommunityManager()
    return manager.validate_large_community(community)


def generate_blackhole_communities(asn: Union[str, int], use_large: bool = True) -> List[str]:
    """Generate blackhole communities - utility function"""
    manager = BGPCommunityManager()
    if isinstance(asn, str):
        if asn.upper().startswith('AS'):
            asn_num = int(asn[2:])
        else:
            asn_num = int(asn)
    else:
        asn_num = int(asn)
    
    return manager.generate_blackhole_communities(asn_num, use_large)


if __name__ == "__main__":
    # Test the community manager
    manager = BGPCommunityManager()
    
    # Test standard communities
    print("=== Standard Communities ===")
    test_communities = ["64512:100", "65535:666", "NO_EXPORT", "12345:200"]
    for comm in test_communities:
        is_valid, comm_type = manager.validate_community(comm)
        print(f"{comm}: {is_valid} ({comm_type.value})")
    
    # Test large communities
    print("\n=== Large Communities ===")
    large_communities = ["64512:1:100", "4200000001:1:200", "65536:0:666"]
    for comm in large_communities:
        is_valid, comm_type = manager.validate_community(comm)
        print(f"{comm}: {is_valid} ({comm_type.value})")
    
    # Test 32-bit ASNs
    print("\n=== 32-bit ASN Tests ===")
    test_asns = ["AS64512", "AS4200000001", "65536", "4294967294", "0", "23456"]
    for asn in test_asns:
        is_valid = manager.validate_asn_32bit(asn)
        is_32bit = manager.is_32bit_asn(asn) if is_valid else False
        print(f"{asn}: valid={is_valid}, 32bit={is_32bit}")
    
    # Test blackhole community generation
    print("\n=== Blackhole Communities ===")
    test_blackhole_asns = [64512, 4200000001, 65536]
    for asn in test_blackhole_asns:
        communities = manager.generate_blackhole_communities(asn, use_large=True)
        print(f"AS{asn}: {communities}")